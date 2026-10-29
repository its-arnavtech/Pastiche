"""Measured worker/chunk/affinity sweeps and sustained CPU-stage workloads."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, wait
import json
import os
from pathlib import Path
import time

from remixer.corpus.generate import TrackSpec, atomic_json, generate_track
from .runtime import LaneMonitor, configured_workers, guarded, process_pool

STAGES = ("corpus", "analysis", "render", "synth")


def stage_unit(stage: str, slot: int, destination: Path, source: dict) -> float:
    """Return audio-seconds actually processed; never count cached work."""
    if stage == "corpus":
        row = generate_track(TrackSpec(100000 + slot, duration=20), destination / f"slot-{slot}", force=True)
        return row["duration"]
    if stage == "analysis":
        from .analyze import analyze_file
        row = analyze_file(source["paths"]["mix"], destination / f"analysis-{slot}.json", force=True,
                           provenance={name: source.get(name) for name in ("synthetic", "augmented", "real")})
        return row["duration_seconds"]
    if stage == "render":
        from .assemble import assemble
        from .render import render
        from remixer.corpus.generate import KEY_NAMES
        tonic, mode = source["key"].split()
        target_key = KEY_NAMES[(KEY_NAMES.index(tonic) + 2) % 12] + " " + mode
        recipe = assemble([source], seed=slot, duration=10, bpm=float(source["bpm"]) * 1.1, key=target_key)
        return render(recipe, destination / f"render-{slot}.wav", force=True)["duration_seconds"]
    if stage == "synth":
        import numpy as np
        from remixer.synth.lab import HeuristicScorer, evaluate_genome, random_genome, render_genome
        genome = random_genome(np.random.default_rng(slot))
        row = evaluate_genome((genome, 22050, HeuristicScorer()))
        return 16 * 60 / genome.bpm
    raise ValueError(f"unknown stage {stage}")


def _chunk(job):
    stage, slot, destination, source, chunk_size = job
    audio_seconds = sum(stage_unit(stage, slot, destination, source) for _ in range(chunk_size))
    return chunk_size, audio_seconds


def measure(stage: str, destination: Path, source: dict, workers: int, chunk_size: int = 1,
            seconds: float = 15, affinity: list[int] | None = None) -> dict:
    if stage not in STAGES or chunk_size < 1 or seconds <= 0:
        raise ValueError("valid stage, positive chunk size and duration required")
    workers = configured_workers(workers)
    if affinity:
        workers = min(workers, len(affinity))
    destination.mkdir(parents=True, exist_ok=True)
    guarded(destination)
    with process_pool(workers, affinity) as pool:
        # Exclude spawn/import/cache priming, then keep one bounded chunk per worker.
        warm = [pool.submit(_chunk, (stage, slot, destination, source, 1)) for slot in range(workers)]
        for future in warm:
            future.result()
        started, units, audio_seconds = time.perf_counter(), 0, 0.0
        with LaneMonitor() as monitor:
            pending = {pool.submit(_chunk, (stage, slot, destination, source, chunk_size)): slot for slot in range(workers)}
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    slot = pending.pop(future)
                    count, duration = future.result()
                    units += count
                    audio_seconds += duration
                    guarded(destination)
                    if time.perf_counter() - started < seconds:
                        pending[pool.submit(_chunk, (stage, slot, destination, source, chunk_size))] = slot
                atomic_json(destination / "checkpoint.json", {"stage": stage, "units": units,
                                                             "audio_seconds": audio_seconds,
                                                             "elapsed": time.perf_counter() - started})
        elapsed = time.perf_counter() - started
    result = {"stage": stage, "workers": workers, "chunk_size": chunk_size, "affinity": affinity,
              "requested_seconds": seconds, "wall_seconds": elapsed, "units": units,
              "units_per_minute": units * 60 / elapsed, "audio_seconds_per_second": audio_seconds / elapsed,
              **monitor.summary()}
    atomic_json(destination / "benchmark.json", result)
    return result


def knee(results: list[dict], tolerance: float = .03) -> dict:
    """Smallest worker count within 3% of observed best throughput."""
    if not results:
        raise ValueError("no tuning measurements")
    peak = max(row["units_per_minute"] for row in results)
    eligible = [row for row in results if row["units_per_minute"] >= peak * (1 - tolerance)]
    return min(eligible, key=lambda row: (row["workers"], row["chunk_size"]))


def tune(corpus: Path, destination: Path, seconds: float = 15, stages: tuple[str, ...] = STAGES,
         max_rounds: int = 6) -> dict:
    import pyarrow.parquet as pq
    from remixer.adapters.cpu_topology import cpu_sets
    source = pq.read_table(corpus / "manifest.parquet").to_pylist()[0]
    topology, budget = cpu_sets(), configured_workers()
    candidates = sorted({1, min(4, budget), min(8, budget), min(12, budget), budget})
    all_rows, best, convergence = [], {}, {}
    destination.mkdir(parents=True, exist_ok=True)
    for stage in stages:
        for workers in candidates:
            row = measure(stage, destination / stage / f"w{workers}-c1", source, workers, seconds=seconds)
            all_rows.append(row)
            atomic_json(destination / "measurements.json", {"rows": all_rows})
            print(json.dumps({"tuning": stage, "workers": workers, "units_per_minute": row["units_per_minute"]}), flush=True)
        selected = knee([row for row in all_rows if row["stage"] == stage])
        for chunk in (2, 4):
            row = measure(stage, destination / stage / f"w{selected['workers']}-c{chunk}", source,
                          selected["workers"], chunk, seconds)
            all_rows.append(row)
        for label in ("performance", "efficiency"):
            affinity = topology.get(label)
            if affinity:
                row = measure(stage, destination / stage / label, source, min(len(affinity), budget), seconds=seconds, affinity=affinity)
                row["affinity_class"] = label
                all_rows.append(row)
        selected = knee([row for row in all_rows if row["stage"] == stage])
        previous_best, stable = selected["units_per_minute"], 0
        rounds = []
        for iteration in range(max_rounds):
            row = measure(stage, destination / stage / f"confirm-{iteration}", source, selected["workers"],
                          selected["chunk_size"], max(seconds, 15), selected["affinity"])
            improvement = row["units_per_minute"] / previous_best - 1
            stable = stable + 1 if improvement < .03 else 0
            previous_best = max(previous_best, row["units_per_minute"])
            rounds.append({"round": iteration, "improvement_over_previous_best": improvement, **row})
            all_rows.append(row)
            if row["units_per_minute"] > selected["units_per_minute"]:
                selected = row
            if stable >= 2:
                break
        best[stage] = {key: selected[key] for key in ("workers", "chunk_size", "affinity", "units_per_minute")}
        convergence[stage] = {"converged": stable >= 2, "rounds": rounds}
        atomic_json(destination / "tuning.json", {"best": best, "convergence": convergence, "topology": topology, "rows": all_rows})
    result = {"best": best, "convergence": convergence, "topology": topology, "rows": all_rows}
    atomic_json(destination / "tuning.json", result)
    return result


def sustain(corpus: Path, destination: Path, seconds: float = 600, tuning: Path | None = None,
            stages: tuple[str, ...] = STAGES) -> dict:
    import pyarrow.parquet as pq
    source = pq.read_table(corpus / "manifest.parquet").to_pylist()[0]
    configured = json.loads(tuning.read_text())["best"] if tuning else {}
    results = []
    for stage in stages:
        settings = configured.get(stage, {})
        # Assignment requests a full-budget sustain even if a smaller pool is
        # slightly more efficient. Record tuned settings alongside this result.
        if stage == "synth":
            from remixer.synth.lab import evolve
            row = evolve(destination / stage, seconds=seconds, workers=configured_workers())
            row.update({"units": row["clips"], "units_per_minute": row["clips_per_minute"],
                        "chunk_size": None, "affinity": None})
        elif stage == "render":
            from .render import render_storm
            row = render_storm(corpus, destination / stage, seconds, configured_workers())
            row.update({"units": row["renders"], "units_per_minute": row["renders_per_minute"],
                        "chunk_size": None, "affinity": None})
        else:
            row = measure(stage, destination / stage, source, configured_workers(),
                          settings.get("chunk_size", 1), seconds, None)
        row["tuned_configuration"] = settings
        results.append(row)
        atomic_json(destination / "sustain.json", {"results": results})
        print(json.dumps({"sustain_complete": stage, "units_per_minute": row["units_per_minute"],
                          "wall_seconds": row["wall_seconds"]}), flush=True)
    return {"results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("tune", "sustain"))
    parser.add_argument("--corpus", type=Path, default=Path(os.environ.get("REMIXER_DATA_DIR", "data")) / "corpus")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--stages", nargs="+", choices=STAGES, default=STAGES)
    parser.add_argument("--tuning", type=Path)
    args = parser.parse_args()
    if args.mode == "tune":
        result = tune(args.corpus, args.output, args.seconds or 15, tuple(args.stages))
    else:
        result = sustain(args.corpus, args.output, args.seconds or 600, args.tuning, tuple(args.stages))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

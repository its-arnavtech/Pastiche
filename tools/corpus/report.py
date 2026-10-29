"""Render measured lane artifacts into the owned CPU-lane Markdown report."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def number(value, digits=2):
    return f"{value:,.{digits}f}" if isinstance(value, (int, float)) else "unavailable"


def scaling_plot(tuning: dict, destination: Path) -> None:
    if not tuning.get("best"):
        return
    os.environ.setdefault("MPLCONFIGDIR", str(Path(os.environ.get("REMIXER_DATA_DIR", "data")) / "cache/matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    figure, axes = plt.subplots(2, 2, figsize=(10, 6), constrained_layout=True)
    for axis, stage in zip(axes.flat, ("corpus", "analysis", "render", "synth")):
        points = [row for row in tuning.get("rows", []) if row["stage"] == stage and not row.get("affinity")]
        for chunk in sorted({row["chunk_size"] for row in points}):
            workers = sorted({row["workers"] for row in points if row["chunk_size"] == chunk})
            rates = [np.median([row["units_per_minute"] for row in points if row["workers"] == worker and row["chunk_size"] == chunk]) for worker in workers]
            axis.plot(workers, rates, "o-", label=f"chunk {chunk}", linewidth=1.2)
        selected = tuning.get("best", {}).get(stage)
        if selected:
            axis.scatter([selected["workers"]], [selected["units_per_minute"]], marker="*", s=130, color="#C45824", label="best observed")
        axis.set(title=stage.capitalize(), xlabel="CPU workers", ylabel="units / minute")
        axis.grid(alpha=.2)
        axis.legend(fontsize=7)
    figure.suptitle("CPU lane scaling under measured concurrent workloads")
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=150)
    plt.close(figure)


def make_report(data: Path, output: Path):
    corpus = read(data / "corpus/benchmark.json")
    analysis = read(data / "analysis/benchmark.json")
    tuning = read(data / "cpu-peak/tuning/tuning.json")
    sustain = read(data / "cpu-peak/sustain/sustain.json")
    baseline = read(data / "npu/sustain/benchmark.json")
    if not baseline:
        baseline = {"results": [read(path) for path in sorted((data / "npu/sustain").glob("*-benchmark.json"))]}
    dual = read(data / "npu/dual/benchmark.json")
    peak_hold = read(data / "npu/peak-hold/benchmark.json")
    phase = read(data / "cpu-peak/runner.json").get("phase", "not started")
    varied = read(data / "corpus-varied/benchmark.json")
    varied_analysis = read(data / "analysis-varied/benchmark.json")
    verification = read(data / "verification/render.json")
    test_verification = read(data / "verification/tests.json")
    lines = ["# CPU and Intel lane measurements", "",
             f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} from local measured artifacts.", "",
             f"Peak sequence phase: **{phase}**. Agent: `gpt-sol`, branch `dev`.", "",
             "## Hardware and method", "",
             "Intel Core Ultra 9 185H, 22 logical / 16 physical cores, Intel Arc iGPU, Intel AI Boost NPU, "
             "23.4 GiB RAM and NVMe. The NVIDIA lane belongs to opus-cc. The configured CPU budget is "
             "17 workers, or 16 while the Intel lane borrows one host thread. Native math threads are "
             "limited to one per worker; multiprocessing uses spawn. The Windows power plan was Balanced "
             "at bootstrap; no power, firmware, driver, fan or clock settings were changed by this lane.", "",
             "Measurements exclude worker warm-up in the tuner. Every timed CPU unit forces actual work; "
             "cache hits are not counted as compute. Full-corpus analysis is resumable and its elapsed "
             "time covers the completed invocation after the checkpointed algorithm restart. Host CPU, "
             "RAM and disk figures include concurrent agents and applications; process-tree RSS is separate. "
             "Missing temperature sensors are reported as unavailable. Throughput differences alone do "
             "not establish thermal or memory-bandwidth limits.", "",
             "The first corpus run used the standalone 10 GiB disk floor while the shared guard was landing. "
             "Subsequent stages use remixer.guards in unleashed mode and atomic checkpoints. All audio "
             "generated here is synthetic; no real taste data is used by the heuristic or random MLP.", "",
             "## Corpus", "",
             f"{corpus.get('tracks', 0)} tracks; {number(corpus.get('audio_seconds', 0) / 3600)} hours; "
             f"{number(corpus.get('wall_seconds'))} wall seconds; **{number(corpus.get('audio_seconds_per_second'))} "
             "audio-seconds / wall-second**. Each has 44.1 kHz stereo PCM16 drums, bass, vocals-like lead, "
             "other, and their exact integer-summed mix, with seeded BPM, key and beat positions.", "",
             f"Host CPU mean {number(corpus.get('system_cpu_mean_percent'))}%, peak "
             f"{number(corpus.get('system_cpu_peak_percent'))}%; process-tree RSS peak "
             f"{number((corpus.get('process_tree_peak_rss_bytes') or 0) / 2**30)} GiB. "
             f"Host write throughput {number((corpus.get('system_disk_write_bytes_per_second') or 0) / 1e6)} MB/s. "
             f"Disk-floor stop: {corpus.get('stopped')}; real library files registered: {corpus.get('registered_real', 0)}.", "",
             "The original baseline uses procedural-v1. The current default generator also varies eight chord "
             "progressions, four kick/snare styles, note rests and hat velocities under procedural-v2. "
             "Legacy seed identities and bytes remain reproducible with --legacy-arrangement. "
             f"Additional procedural-v2 validation tracks completed: {varied.get('tracks', 0)}; "
             f"their track key accuracy: {number((varied_analysis.get('key_accuracy') or 0) * 100)}%; "
             f"BPM MAE: {number(varied_analysis.get('mean_bpm_error'), 3)}.", "",
             "## Analysis accuracy", ""]
    if analysis:
        lines += [f"Analyzed {analysis.get('items')} mixes/stems ({analysis.get('tracks')} tracks). "
                  f"Mean absolute BPM error: **{number(analysis.get('mean_bpm_error'), 3)} BPM**. "
                  f"Exact tonic-and-mode accuracy: **{number((analysis.get('key_accuracy') or 0) * 100)}%**. "
                  f"Throughput {number(analysis.get('tracks_per_minute'))} tracks/minute or "
                  f"{number(analysis.get('items_per_minute'))} mixes/stems per minute; errors: {len(analysis.get('errors', []))}.", ""]
        lines += [f"Method: {analysis.get('accuracy_method', 'independent mix analysis')}. "
                  f"Mix-only key accuracy remains {number((analysis.get('mix_key_accuracy', analysis.get('key_accuracy')) or 0) * 100)}%; "
                  f"mix-only BPM MAE {number(analysis.get('mix_mean_bpm_error', analysis.get('mean_bpm_error')), 3)}. "
                  f"Post-analysis refinement took {number(analysis.get('refinement_seconds', 0))} seconds and is separate from "
                  "the original throughput timing. Original baseline estimates are retained in data/analysis/baseline-v2.json.", ""]
    else:
        lines += ["Full-corpus analysis is still running. Accuracy is measured from estimated audio features, never copied from ground truth.", ""]
    lines += ["## Tuning and knees", "", "Knee: smallest worker count within 3% of the observed best. Confirmation stops after two successive "
              "rounds improve the previous best by less than 3%. Full-budget sustains use unrestricted scheduling; "
              "P/E affinity comparisons remain separate.", "",
              "| Stage | Selected workers | Chunk | Affinity | Tuned units/min | Converged |", "|---|---:|---:|---|---:|---|"]
    for stage, settings in tuning.get("best", {}).items():
        lines.append(f"| {stage} | {settings['workers']} | {settings['chunk_size']} | {settings.get('affinity') or 'OS scheduler'} | "
                     f"{number(settings['units_per_minute'])} | {tuning['convergence'][stage]['converged']} |")
    topology = tuning.get("topology", {})
    lines += ["", "A selected count at the lane ceiling does not establish a hardware scaling plateau. "
              "The initial unrestricted sweeps still gained more than 3% at the largest allowed count for "
              "corpus, render and synth; those selections are budget-limited. Analysis gained only about 2.2% "
              "from 12 to 16 workers, so its observed worker knee is 12. Confirmation convergence concerns "
              "the best configuration's measured throughput, separately from worker-count scaling.", "",
              "| Stage | Affinity class | Workers | Units/min | Host CPU mean % |", "|---|---|---:|---:|---:|"]
    for row in tuning.get("rows", []):
        if row.get("affinity_class"):
            lines.append(f"| {row['stage']} | {row['affinity_class']} | {row['workers']} | {number(row['units_per_minute'])} | {number(row.get('system_cpu_mean_percent'))} |")
    lines += ["", f"Topology discovery: {topology.get('reason') or ('P=' + str(topology.get('performance')) + ', E=' + str(topology.get('efficiency')))}.", "",
              "Every worker/chunk/affinity configuration and confirmation round is preserved in "
              "`data/cpu-peak/tuning/tuning.json`. Units are generated tracks, analyzed files, rendered recipes, "
              "or scored synth clips, respectively. The corpus tuning unit is a 20-second fresh track; analysis "
              "uses a complete corpus mix; render tuning uses a 10-second recipe; synth tuning scores one clip.", "",
              "## Sustained CPU stages", "",
              "| Stage | Workers | Seconds | Units/min | Host CPU mean / peak % | Tree RSS GiB | Host RAM GiB | Read / write MB/s |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in sustain.get("results", []):
        lines.append(f"| {row['stage']} | {row['workers']} | {number(row['wall_seconds'])} | {number(row['units_per_minute'])} | "
                     f"{number(row.get('system_cpu_mean_percent'))} / {number(row.get('system_cpu_peak_percent'))} | "
                     f"{number((row.get('process_tree_peak_rss_bytes') or 0) / 2**30)} | {number((row.get('system_memory_peak_bytes') or 0) / 2**30)} | "
                     f"{number((row.get('system_disk_read_bytes_per_second') or 0) / 1e6)} / {number((row.get('system_disk_write_bytes_per_second') or 0) / 1e6)} |")
    lines += ["", "| Stage | CPU temperature C | NVIDIA peak temperature C | NVIDIA observed throttle reasons |",
              "|---|---:|---:|---|"]
    for row in sustain.get("results", []):
        lines.append(f"| {row['stage']} | {number(row.get('cpu_temperature_c'))} | "
                     f"{number(row.get('gpu_temperature_peak_c'))} | "
                     f"{', '.join(row.get('gpu_throttle_reasons', [])) or 'none observed'} |")
    lines += ["", "These are shared host/NVIDIA observations during each CPU measurement, not Intel device "
              "temperatures. The hardware thermal/power flags are logged under unleashed mode; "
              "they do not establish a CPU-stage thermal limit.", ""]
    gpu_rows = []
    gpu_path = data / "cpu-peak/gpu-overlap.jsonl"
    if gpu_path.exists():
        with gpu_path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    gpu_rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # concurrent writer may not have finished its last line
    lines += ["", "| Stage | NVIDIA observed samples | NVIDIA mean % | Samples above 90% | iGPU mean % |", "|---|---:|---:|---:|---:|"]
    for row in sustain.get("results", []):
        times = [sample["wall_time"] for sample in row.get("sample_series", [])]
        timing_start = row.get("timing_started_wall_time", min(times) if times else None)
        timing_end = row.get("timing_ended_wall_time", max(times) if times else None)
        context = [sample for sample in gpu_rows if timing_start is not None and timing_start <= sample["wall_time"] <= timing_end]
        values = [sample["gpu_utilization_percent"] for sample in context if sample.get("gpu_utilization_percent") is not None]
        igpu = [sample["igpu_utilization_percent"] for sample in context if sample.get("igpu_utilization_percent") is not None]
        lines.append(f"| {row['stage']} | {len(values)} | {number(sum(values) / len(values) if values else None)} | "
                     f"{number(100 * sum(value > 90 for value in values) / len(values) if values else None)}% | "
                     f"{number(sum(igpu) / len(igpu) if igpu else None)} |")
    lines += ["", "NVIDIA overlap is observed through NVML or the existing Windows PDH adapter. NVML can report "
              "Unknown when idle; PDH zeroes are retained as zeroes. Missing/partial sampling cannot certify "
              "a synchronized ten-minute GPU run. NPU has no Windows utilization counter here; device execution "
              "and inferences/second are recorded directly.", ""]
    measured_rows = [*tuning.get("rows", []), *sustain.get("results", [])]
    max_read = max((row.get("system_disk_read_bytes_per_second", 0) for row in measured_rows), default=0)
    max_write = max((row.get("system_disk_write_bytes_per_second", 0) for row in measured_rows), default=0)
    lines += [f"Maximum observed configuration-average host disk rates: read {number(max_read / 1e6)} MB/s; "
              f"write {number(max_write / 1e6)} MB/s. These are maxima across averaged measurement windows, "
              "not instantaneous NVMe device peaks.", ""]
    lines += ["", "Render sustain uses cross-source recipes with loudness matching and actual Rubber Band processing. "
              "Synth sustain evolves full populations with selection, crossover and mutation, saves each generation, "
              "and exposes a FitnessScorer protocol. The measured sustain used heuristic fitness; a separate "
              "single-parent CPU CLAP backend now supports trained taste fitness without duplicating the encoder in workers.", "",
              f"Full storm-recipe verification: {verification.get('byte_identical', 'pending')}; "
              f"duration {number(verification.get('duration_seconds'))} seconds. Two forced renders are compared "
              "with each other and the sustained-run output, not merely with a cached render.", "",
              "Observed limits: analysis shows an early scaling plateau with full-track hashing, memory traffic and "
              "reads; the remaining CPU kernels continue gaining up to their allowed worker budget. Large host RAM "
              "occupancy and competing GPU/iGPU traffic were present, so these data do not isolate memory bandwidth "
              "from CPU, cache or disk latency. CPU thermals cannot be assigned as the limiter without a temperature "
              "reader. Every configuration and its concurrent host counters remain available for that distinction.", "",
              "## Intel device runs", "", "| Mode | Requested / executed | Device | Seconds | Embeddings/s | Reference max error | Fallback |", "|---|---|---|---:|---:|---:|---|"]
    for mode, result in (("per-device", baseline), ("simultaneous async", dual), ("CPU peak hold", peak_hold)):
        for row in result.get("results", []):
            lines.append(f"| {mode} | {row['requested_device']} / {row['executed_device']} | {row['full_device_name']} | "
                         f"{number(row['wall_seconds'])} | {number(row['inferences_per_second'])} | "
                         f"{number(row['max_reference_error'], 6)} | {row.get('fallback_reason') or 'none'} |")
    lines += ["", "The IR is a seeded 512→256→64→1 ReLU MLP with static batch 128. It is an untrained synthetic "
              "load/placement probe, not the owner's taste model. Device compilation and numeric validation are excluded "
              "from sustained timing. Simultaneous mode feeds bounded asynchronous request queues from one host loop. "
              "Intel GPU full names are validated before compilation; NVIDIA execution is excluded.", "",
              "## Limits and remaining work", "",
              "CPU temperatures and thermal-throttle attribution require an available sensor reader. Host disk rates "
              "are aggregate OS counters, not lane-isolated bandwidth. Worker sweeps identify scaling limits; they "
              "cannot alone distinguish memory bandwidth, cache, power limits and thermal throttling. The GPU coordinator's "
              "combined bench record is needed to certify a synchronized all-engines result. A held GPU lock proves ownership, "
              "not sustained GPU utilization. See `docs/PEAK_REPORT.md` for the coordinator's evidence.", "",
              "The late T-017 checkpoint failed validation: every parameter was nonfinite, as were all values in "
              "three sampled CLAP checkpoint files. FP16 autocast underflowed the log-mel floor. The front end now "
              "runs power/mel/log calculations in FP32; a new embedding/cache/index version isolates old artifacts. "
              "A real CPU CLAP forward produced finite features and a finite 512-dimensional embedding "
              "(data/verification/clap-fp32.json). The coordinator must restart embedding and retrain before the "
              "production checkpoint can be used. Recovery is tracked in T-030. Old artifacts are retained.", "",
              "Trained OpenVINO export and synth fitness adapters preserve the trainer's exact GELU, biases, "
              "sigmoid and CLAP version. Fixture tests compare NumPy/OpenVINO predictions with PyTorch. "
              "Automatic selection warns and retains the labeled random/heuristic backend when weights are "
              "invalid; explicit trained selection fails. No learned-throughput result is claimed from corrupt "
              "weights. Training rejects nonfinite inputs/loss/weights and replants current-version synthetic "
              "ratings when only old-version ratings exist.", "",
              "## Verification and handoff", "",
              f"Repository suite: {test_verification.get('passed', 'pending')} passed, "
              f"{test_verification.get('skipped', 'pending')} skipped, "
              f"{test_verification.get('deselected', 'pending')} deselected. "
              "The skipped browser extra and separately marked scale test remain distinct from CPU/NPU verification. "
              "Exact 30-second render reproduction and deterministic evolutionary resume are checked. "
              "CPU/NPU locks were released for the coordinator's T-018 run. No new user blocker was introduced; "
              "existing optional power-mode, merge-worktree cleanup and idle-time environment sync are listed in "
              "docs/NEEDS_USER.md.", "",
              "## Reproduce", "", "```powershell", "uv run remixer corpus generate --n 500 --legacy-arrangement", "uv run remixer analyze", "uv run remixer analyze --queue",
              "uv run remixer cpu tune --output data/cpu-peak/tuning", "uv run remixer cpu sustain --output data/cpu-peak/sustain --tuning data/cpu-peak/tuning/tuning.json --seconds 600",
              "uv run remixer npu --seconds 600 --random-scorer", "uv run python tools/corpus/report.py", "uv run pytest", "```", "",
              "Acquire CPU/NPU locks through agentctl before heavy runs; the peak coordinator acquires GPU, CPU, NPU in that order. "
              "Use REMIXER_DATA_DIR for an alternate data root. Source music remains read-only.", "", "## Versions", ""]
    for package in ("numpy", "scipy", "soundfile", "pyarrow", "pedalboard", "pyloudnorm", "openvino"):
        lines.append(f"- {package}: {importlib.metadata.version(package)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    plot = output.with_name("cpu-lane-scaling.png")
    scaling_plot(tuning, plot)
    if plot.exists():
        lines += ["", "![CPU worker and chunk scaling](cpu-lane-scaling.png)", "",
                  "Curves show median repeated measurements for each worker/chunk pair; stars show the selected "
                  "best observed result. Concurrent GPU activity and memory pressure changed during the sweep, "
                  "so this is an operational scaling record rather than an isolated processor scaling law.", ""]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(os.environ.get("REMIXER_DATA_DIR", "data")))
    parser.add_argument("--output", type=Path, default=Path("docs/reports/cpu-lane.md"))
    args = parser.parse_args()
    make_report(args.data, args.output)


if __name__ == "__main__":
    main()

"""Deterministic Rubber Band rendering and sustained parallel render storm."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, wait
import json
import math
import os
from pathlib import Path
import time

import numpy as np
from pedalboard import time_stretch
import pyloudnorm as pyln
from scipy import signal
import soundfile as sf

from remixer.corpus.generate import atomic_json, atomic_replace, file_hash
from .assemble import Recipe, assemble
from .runtime import LaneMonitor, configured_workers, guarded, process_pool

VERSION = "rubberband-render-v1"


def render(recipe: Recipe, output: str | Path, *, force: bool = False) -> dict:
    output = Path(output)
    for pick in recipe.stems:
        source = Path(pick.path)
        if output.resolve() == source.resolve() or (output.exists() and source.exists() and output.samefile(source)):
            raise ValueError("render output must never overwrite source audio")
    guarded(output.parent)
    checkpoint = output.with_suffix(".json")
    if checkpoint.exists() and output.exists() and not force:
        cached = json.loads(checkpoint.read_text(encoding="utf-8"))
        if cached.get("recipe_id") == recipe.identity and cached.get("version") == VERSION and cached.get("sha256") == file_hash(output):
            return cached
    if not recipe.stems or recipe.bpm <= 0 or recipe.sample_rate < 2000:
        raise ValueError("invalid recipe")
    rendered = []
    for pick in recipe.stems:
        if pick.start_seconds < 0 or pick.end_seconds <= pick.start_seconds or pick.source_bpm <= 0 or pick.offset_seconds < 0:
            raise ValueError("invalid stem time range, offset or BPM")
        path = Path(pick.path)
        if file_hash(path) != pick.source_hash:
            raise ValueError("source hash changed; recipe must pin exact audio")
        info = sf.info(path)
        if pick.end_seconds > info.duration + 1 / info.samplerate:
            raise ValueError("recipe exceeds source duration")
        audio, sr = sf.read(path, start=round(pick.start_seconds * info.samplerate),
                            stop=round(pick.end_seconds * info.samplerate), dtype="float32", always_2d=True)
        if audio.shape[1] == 1:
            audio = np.repeat(audio, 2, axis=1)
        if audio.shape[1] != 2:
            raise ValueError("renderer supports mono/stereo sources")
        if sr != recipe.sample_rate:
            divisor = math.gcd(sr, recipe.sample_rate)
            audio = signal.resample_poly(audio, recipe.sample_rate // divisor, sr // divisor, axis=0)
        ratio = recipe.bpm / pick.source_bpm
        if ratio != 1 or pick.semitones != 0:
            audio = time_stretch(np.ascontiguousarray(audio.T), recipe.sample_rate, stretch_factor=ratio,
                                 pitch_shift_in_semitones=pick.semitones).T
        audio = np.asarray(audio, dtype=np.float64)
        if len(audio) >= recipe.sample_rate * .4:
            lufs = pyln.Meter(recipe.sample_rate).integrated_loudness(audio)
            if np.isfinite(lufs):
                audio *= 10 ** ((recipe.target_lufs - lufs + pick.gain_db) / 20)
        else:
            audio *= 10 ** (pick.gain_db / 20)
        rendered.append((round(pick.offset_seconds * recipe.sample_rate), audio))
    frames = max(offset + len(audio) for offset, audio in rendered)
    mix = np.zeros((frames, 2), dtype=np.float64)
    for offset, audio in rendered:
        mix[offset:offset+len(audio)] += audio / len(rendered)
    for effect, value in recipe.effects:
        if effect == "gain_db":
            mix *= 10 ** (value / 20)
        elif effect in {"lowpass_hz", "highpass_hz"}:
            sos = signal.butter(3, value, btype="lowpass" if effect.startswith("low") else "highpass",
                                fs=recipe.sample_rate, output="sos")
            mix = signal.sosfilt(sos, mix, axis=0)
        elif effect == "delay_seconds":
            delay = round(value * recipe.sample_rate)
            if delay < 1:
                raise ValueError("delay must be positive")
            if delay < len(mix):
                mix[delay:] += .2 * mix[:-delay].copy()
        else:
            raise ValueError(f"unsupported deterministic effect: {effect}")
    peak = np.max(np.abs(mix))
    if peak > .98:
        mix *= .98 / peak
    temp = output.with_suffix(f".{os.getpid()}.partial.wav")
    sf.write(temp, np.rint(mix * 32767).astype(np.int16), recipe.sample_rate, subtype="PCM_16")
    atomic_replace(temp, output)
    row = {"recipe_id": recipe.identity, "version": VERSION, "sha256": file_hash(output),
           "duration_seconds": frames / recipe.sample_rate, "synthetic": recipe.synthetic,
           "augmented": recipe.augmented, "recipe": recipe.to_dict()}
    atomic_json(checkpoint, row)
    return row


def _render_job(job):
    recipe, output = job
    return render(recipe, output, force=True)


def render_storm(corpus: Path, destination: Path, seconds: float = 600, workers: int | None = None,
                 duration: float = 30, seed: int = 0) -> dict:
    import pyarrow.parquet as pq
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    rows = pq.read_table(corpus / "manifest.parquet").to_pylist()
    workers = configured_workers(workers)
    destination.mkdir(parents=True, exist_ok=True)
    completed, audio_seconds = 0, 0.0
    with LaneMonitor() as monitor, process_pool(workers) as pool:
        warm = [pool.submit(_render_job, (assemble(rows, seed + slot, duration, bpm=123),
                                         destination / f"slot-{slot}.wav")) for slot in range(workers)]
        for future in warm:
            future.result()
        started, started_wall_time = time.perf_counter(), time.time()
        pending, sequence = {}, 0
        while time.perf_counter() - started < seconds or pending:
            while time.perf_counter() - started < seconds and len(pending) < workers:
                recipe = assemble(rows, seed + sequence, duration, bpm=123)
                slot = sequence % workers
                # Reuse a slot only after its prior render completes.
                while any(existing == slot for existing in pending.values()):
                    slot = (slot + 1) % workers
                pending[pool.submit(_render_job, (recipe, destination / f"slot-{slot}.wav"))] = slot
                sequence += 1
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                pending.pop(future)
                row = future.result()
                completed += 1
                audio_seconds += row["duration_seconds"]
                atomic_json(destination / "checkpoint.json", {"completed": completed, "last_recipe_id": row["recipe_id"]})
    elapsed = time.perf_counter() - started
    result = {"stage": "render", "workers": workers, "wall_seconds": elapsed, "renders": completed,
              "timing_started_wall_time": started_wall_time, "timing_ended_wall_time": time.time(),
              "renders_per_minute": completed * 60 / elapsed, "audio_seconds_per_second": audio_seconds / elapsed,
              **monitor.summary()}
    atomic_json(destination / "benchmark.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path)
    parser.add_argument("--corpus", type=Path, default=Path(os.environ.get("REMIXER_DATA_DIR", "data")) / "corpus")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=600)
    parser.add_argument("--workers", type=int)
    args = parser.parse_args()
    if args.recipe:
        result = render(Recipe.from_dict(json.loads(args.recipe.read_text())), args.output)
    else:
        result = render_storm(args.corpus, args.output, args.seconds, args.workers)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

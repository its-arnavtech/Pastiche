"""Bounded-memory procedural corpus. Run ``python -m remixer.corpus.generate``."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict, dataclass
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import time

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import soundfile as sf

VERSION = "procedural-v1"
STEMS = ("drums", "bass", "vocals", "other")
KEY_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
PROGRESSIONS = ((0, 5, 3, 4), (0, 3, 4, 0), (5, 3, 0, 4), (0, 4, 5, 3),
                (1, 4, 0, 5), (0, 2, 3, 4), (0, 3, 1, 4), (0, 5, 1, 4))


@dataclass(frozen=True)
class TrackSpec:
    seed: int
    duration: float = 180.0
    sample_rate: int = 44100
    bpm: int | None = None
    tonic: int | None = None
    minor: bool | None = None
    arrangement: int | None = None

    def resolved(self) -> dict:
        if self.duration <= 0 or self.sample_rate < 2000:
            raise ValueError("duration must be positive and sample_rate >= 2000")
        rng = np.random.default_rng(self.seed)
        bpm = int(self.bpm if self.bpm is not None else rng.integers(70, 176))
        tonic = int(self.tonic if self.tonic is not None else rng.integers(12))
        minor = bool(self.minor if self.minor is not None else rng.integers(2))
        if not 30 <= bpm <= 300 or not 0 <= tonic < 12:
            raise ValueError("invalid BPM or tonic")
        result = {**asdict(self), "bpm": bpm, "tonic": tonic, "minor": minor}
        if self.arrangement is None:
            result.pop("arrangement")  # Preserve original identities and audio.
        elif not 0 <= self.arrangement < 8:
            raise ValueError("arrangement must be in 0..7")
        return result


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, sort_keys=True, indent=2), encoding="utf-8")
    atomic_replace(temp, path)


def atomic_replace(source: Path, destination: Path) -> None:
    """Windows readers/antivirus can briefly deny delete sharing on replace."""
    for attempt in range(40):
        try:
            source.replace(destination)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(min(.025 * 2**min(attempt, 4), .25))


def _stereo(signal: np.ndarray, pan: float = 0.0) -> np.ndarray:
    return np.column_stack((signal * (1 - pan * .3), signal * (1 + pan * .3)))


def synth_block(spec: dict, start: int, count: int) -> dict[str, np.ndarray]:
    """Absolute sample indices make synthesis independent of block boundaries."""
    sr, bpm, seed = spec["sample_rate"], spec["bpm"], spec["seed"]
    t = np.arange(start, start + count, dtype=np.float64) / sr
    beat = t * bpm / 60
    phase = np.mod(beat, 1) * 60 / bpm
    # Stateless deterministic noise: independent of rendering block size.
    indices = np.arange(start, start + count, dtype=np.uint64)
    bits = (indices + np.uint64(seed % (2**32))) * np.uint64(6364136223846793005) + np.uint64(1442695040888963407)
    noise = ((bits >> np.uint64(32)).astype(np.float64) / 2**31 - 1)
    kick = np.sin(2 * np.pi * (48 * phase + 55 * .025 * (1 - np.exp(-phase / .025)))) * np.exp(-phase * 22)
    snare_phase = np.mod(beat - 1, 2) * 60 / bpm
    snare = noise * np.exp(-snare_phase * 38) * .5
    hat_phase = np.mod(beat * 2, 1) * 30 / bpm
    previous_bits = (indices - np.uint64(1) + np.uint64(seed % (2**32))) * np.uint64(6364136223846793005) + np.uint64(1442695040888963407)
    previous_noise = ((previous_bits >> np.uint64(32)).astype(np.float64) / 2**31 - 1)
    hats = (noise - previous_noise) * np.exp(-hat_phase * 130) * .1
    # Diatonic progression: tonic, submediant, subdominant, dominant.
    scale = np.array([0, 2, 3, 5, 7, 8, 10] if spec["minor"] else [0, 2, 4, 5, 7, 9, 11])
    progression = np.array(PROGRESSIONS[spec.get("arrangement", 0)])
    degree = progression[(beat.astype(np.int64) // 16) % 4]
    root = 36 + spec["tonic"] + scale[degree]
    # Analytic phase resets on notes avoid cumulative integration across blocks.
    freq = 440 * 2.0 ** ((root - 69) / 12)
    bass = (np.sin(2 * np.pi * freq * phase) + .22 * np.sin(4 * np.pi * freq * phase)) * np.exp(-phase * 4) * .22
    pad = np.zeros(count)
    for offset in (0, 2, 4):
        midi = 60 + spec["tonic"] + scale[(degree + offset) % 7] + 12 * ((degree + offset) // 7)
        pad += np.sin(2 * np.pi * (440 * 2.0 ** ((midi - 69) / 12)) * t) * .034
    note_index = (beat * 2).astype(np.int64)
    melody_degree = (note_index * (seed % 3 + 1) + seed) % 7
    midi = 72 + spec["tonic"] + scale[melody_degree]
    frequency = 440 * 2.0 ** ((midi - 69) / 12)
    local = np.mod(beat * 2, 1) * 30 / bpm
    envelope = (1 - np.exp(-local * 150)) * np.exp(-local * 9)
    lead = (np.sin(2 * np.pi * frequency * local) + .25 * np.sin(4 * np.pi * frequency * local)) * envelope * .12
    if "arrangement" in spec:
        style = spec["arrangement"] % 4
        kick_patterns = ((1, 0, 1, 0, 1, 0, 1, 0), (1, 0, 0, 1, 1, 0, 1, 0),
                         (1, 0, 0, 0, 1, 0, 0, 0), (1, 0, 1, 1, 1, 0, 1, 1))
        half_phase = np.mod(beat * 2, 1) * 30 / bpm
        kick = (np.sin(2 * np.pi * (48 * half_phase + 55 * .025 * (1 - np.exp(-half_phase / .025))))
                * np.exp(-half_phase * 22) * np.asarray(kick_patterns[style])[note_index % 8])
        hats *= np.where(note_index % 2 == 0, 1, .55 + .1 * (seed % 4))
        lead *= np.where((note_index + seed) % (5 + style) == 0, 0, 1)
        if style == 2:
            snare *= (beat.astype(int) % 4 == 3)
    fade = np.minimum(1, np.minimum(t * 10, (spec["duration"] - t) * 5)).clip(0, 1)
    return {"drums": _stereo((kick * .22 + snare + hats) * fade),
            "bass": _stereo(bass * fade), "vocals": _stereo(lead * fade, -.35),
            "other": _stereo(pad * fade, .45)}


def generate_track(spec: TrackSpec, destination: str | Path, block_size: int = 65536, *, force: bool = False) -> dict:
    values = spec.resolved()
    version = VERSION if spec.arrangement is None else "procedural-v2"
    identity = hashlib.sha256((version + json.dumps(values, sort_keys=True)).encode()).hexdigest()
    directory = Path(destination) / identity
    checkpoint = directory / "track.json"
    if checkpoint.exists() and not force:
        row = json.loads(checkpoint.read_text(encoding="utf-8"))
        if all(Path(path).exists() and file_hash(Path(path)) == row["hashes"][name]
               for name, path in row["paths"].items()):
            return row
    directory.mkdir(parents=True, exist_ok=True)
    frames = round(spec.duration * spec.sample_rate)
    needed = frames * 2 * 2 * 5
    if shutil.disk_usage(directory).free < 10 * 1024**3 + needed:
        raise OSError("disk floor: insufficient space above 10 GiB for next track")
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    paths = {name: directory / f"{name}.wav" for name in (*STEMS, "mix")}
    temps = {name: path.with_suffix(".partial.wav") for name, path in paths.items()}
    with ExitStack() as stack:
        writers = {name: stack.enter_context(sf.SoundFile(path, mode="w", samplerate=spec.sample_rate,
                                                         channels=2, subtype="PCM_16"))
                   for name, path in temps.items()}
        for start in range(0, frames, block_size):
            stems = synth_block(values, start, min(block_size, frames - start))
            quantized = {name: np.rint(audio * 24000).clip(-32768, 32767).astype(np.int16)
                         for name, audio in stems.items()}
            mix = sum(audio.astype(np.int32) for audio in quantized.values())
            if np.max(np.abs(mix)) > 32767:
                raise ValueError("synth mix clipped")
            for name, audio in quantized.items():
                writers[name].write(audio)
            writers["mix"].write(mix.astype(np.int16))
    for name, temp in temps.items():
        atomic_replace(temp, paths[name])
    row = {**values, "track_id": identity, "version": version, "synthetic": True,
           "augmented": False, "real": False,
           "key": KEY_NAMES[values["tonic"]] + (" minor" if values["minor"] else " major"),
           "beat_positions": np.arange(0, spec.duration, 60 / values["bpm"]).tolist(),
           "stem_layout": list(STEMS), "paths": {name: str(path.resolve()) for name, path in paths.items()},
           "hashes": {name: file_hash(path) for name, path in paths.items()}}
    if spec.arrangement is not None:
        row.update({"chord_progression_degrees": list(PROGRESSIONS[spec.arrangement]),
                    "drum_pattern": spec.arrangement % 4})
    atomic_json(checkpoint, row)
    return row


def _generate_job(job: tuple) -> dict:
    return generate_track(*job)


def write_manifest(destination: Path, rows: list[dict]) -> Path:
    path = destination / "manifest.parquet"
    temp = path.with_suffix(".tmp.parquet")
    pq.write_table(pa.Table.from_pylist(sorted(rows, key=lambda row: row["track_id"])), temp)
    atomic_replace(temp, path)
    return path


def scan_library(destination: Path, library: Path | None = None) -> int:
    """Register metadata locally; never modify source files or print their paths."""
    if library is None:
        library = Path(os.environ.get("REMIXER_LIBRARY", str(Path.home() / "Music")))
    rows = []
    if library.is_dir():
        for path in sorted(library.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".aac"}:
                rows.append({"path": str(path.resolve()), "bytes": path.stat().st_size,
                             "real": True, "synthetic": False, "augmented": False})
    if rows:
        pq.write_table(pa.Table.from_pylist(rows), destination / "real-library.parquet")
    return len(rows)


def generate_corpus(destination: Path, n: int = 500, seed: int = 0, workers: int | None = None,
                    min_duration: float = 120, max_duration: float = 300, sample_rate: int = 44100,
                    varied: bool = True) -> dict:
    from remixer.cpu.runtime import LaneMonitor, configured_workers, guarded, process_pool
    if n < 1 or min_duration <= 0 or max_duration < min_duration:
        raise ValueError("invalid corpus size or duration range")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    workers = configured_workers(workers)
    rng = np.random.default_rng(seed)
    jobs = []
    for i in range(n):
        duration = float(rng.uniform(min_duration, max_duration))
        # Cycle all arrangements before seeded permutations; even small batches
        # exercise different harmony, syncopation, note rests and velocities.
        arrangement = (i + seed) % 8 if varied else None
        jobs.append((TrackSpec(seed + i, duration, sample_rate, arrangement=arrangement), destination))
    rows, stopped = [], None
    started = time.perf_counter()
    with LaneMonitor() as monitor, process_pool(workers) as pool:
        # Bounded submission leaves at most one in-flight track per worker.
        pending = {}
        iterator = iter(jobs)
        from concurrent.futures import FIRST_COMPLETED, wait
        while True:
            while len(pending) < workers and not stopped:
                job = next(iterator, None)
                if job is None:
                    break
                try:
                    guarded(destination)
                except OSError as exc:
                    stopped = str(exc)
                    break
                pending[pool.submit(_generate_job, job)] = job
            if not pending:
                break
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                pending.pop(future)
                try:
                    row = future.result()
                except OSError as exc:
                    stopped = str(exc)
                    continue
                rows.append(row)
                write_manifest(destination, rows)
                print(json.dumps({"stage": "corpus", "completed": len(rows), "target": n}), flush=True)
    elapsed = time.perf_counter() - started
    result = {"stage": "corpus", "tracks": len(rows), "workers": workers, "wall_seconds": elapsed,
              "audio_seconds": sum(row["duration"] for row in rows), "stopped": stopped,
              "registered_real": scan_library(destination), **monitor.summary()}
    result["audio_seconds_per_second"] = result["audio_seconds"] / elapsed
    atomic_json(destination / "benchmark.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(os.environ.get("REMIXER_DATA_DIR", "data")) / "corpus")
    parser.add_argument("--n", type=int, default=500)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--min-duration", type=float, default=120)
    parser.add_argument("--max-duration", type=float, default=300)
    parser.add_argument("--sample-rate", type=int, default=44100)
    parser.add_argument("--legacy-arrangement", action="store_true")
    args = parser.parse_args()
    print(json.dumps(generate_corpus(args.output, args.n, args.seed, args.workers,
                                      args.min_duration, args.max_duration, args.sample_rate,
                                      varied=not args.legacy_arrangement), indent=2))


if __name__ == "__main__":
    main()

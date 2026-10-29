"""Memory-mapped WAV analysis, window features and ground-truth evaluation."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, wait
import hashlib
import json
import math
import os
from pathlib import Path
import time

import numpy as np
import pyloudnorm as pyln
from scipy import signal
from scipy.io import wavfile
import soundfile as sf

from remixer.corpus.generate import KEY_NAMES, atomic_json, file_hash
from .runtime import LaneMonitor, configured_workers, guarded, process_pool

VERSION = "analysis-v3"
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def _gated_loudness(energies: np.ndarray) -> float | None:
    if not len(energies):
        return None
    if energies.shape[1] > 5:
        raise ValueError("LUFS supports up to five ordered channels")
    gains = np.array([1, 1, 1, 1.41, 1.41])[:energies.shape[1]]
    block_loudness = -.691 + 10 * np.log10(energies @ gains + 1e-30)
    absolute = energies[block_loudness >= -70]
    if not len(absolute):
        return None
    relative_gate = -.691 + 10 * np.log10(absolute.mean(axis=0) @ gains + 1e-30) - 10
    selected = energies[(block_loudness >= -70) & (block_loudness >= relative_gate)]
    return float(-.691 + 10 * np.log10(selected.mean(axis=0) @ gains + 1e-30)) if len(selected) else None


def estimate_key(chroma: np.ndarray) -> tuple[str | None, float]:
    if np.sum(chroma) <= 1e-12:
        return None, 0.0
    normalized = chroma - chroma.mean()
    scores = []
    for minor, profile in ((False, MAJOR), (True, MINOR)):
        for tonic in range(12):
            template = np.roll(profile, tonic)
            centered = template - template.mean()
            score = float(np.dot(normalized, centered) / (np.linalg.norm(normalized) * np.linalg.norm(centered) + 1e-12))
            scores.append((score, tonic, minor))
    score, tonic, minor = max(scores)
    return KEY_NAMES[tonic] + (" minor" if minor else " major"), score


def _features(audio: np.ndarray, sample_rate: int) -> tuple[dict, np.ndarray]:
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    # Resample in bounded five-second windows, not a whole stem per process.
    divisor = math.gcd(sample_rate, 11025)
    low = signal.resample_poly(mono, 11025 // divisor, sample_rate // divisor)
    nfft = 4096
    if len(low) < nfft:
        low = np.pad(low, (0, nfft - len(low)))
    _, _, stft = signal.stft(low, fs=11025, nperseg=nfft, noverlap=nfft // 2, boundary=None)
    power = np.abs(stft)**2
    frequencies = np.fft.rfftfreq(nfft, 1 / 11025)
    spectrum = power.mean(axis=1)
    valid = (frequencies >= 45) & (frequencies <= 4500)
    midi = np.rint(69 + 12 * np.log2(frequencies[valid] / 440)).astype(int)
    chroma = np.bincount(midi % 12, weights=spectrum[valid], minlength=12)
    total = spectrum.sum() + 1e-20
    return {"rms": float(np.sqrt(np.mean(audio**2))),
            "peak": float(np.max(np.abs(audio))),
            "spectral_centroid_hz": float(np.dot(frequencies, spectrum) / total),
            "zero_crossing_rate": float(np.mean(mono[:-1] * mono[1:] < 0)) if len(mono) > 1 else 0,
            "chroma": chroma.tolist()}, low


def estimate_tempo(low: np.ndarray, sample_rate: int = 11025) -> tuple[float | None, list[float]]:
    if len(low) < sample_rate or np.max(np.abs(low)) < 1e-8:
        return None, []
    hop = 128
    # Low-band novelty favors kicks over eighth-note hats and melody notes.
    filtered = signal.sosfilt(signal.butter(3, 180, fs=sample_rate, output="sos"), low)
    frames = len(filtered) // hop
    energy = np.sqrt(np.mean(filtered[:frames * hop].reshape(frames, hop)**2, axis=1))
    onset = np.maximum(0, np.diff(energy, prepend=energy[0]))
    autocorr = signal.fftconvolve(onset, onset[::-1], mode="full")[len(onset)-1:]
    minimum = max(1, int(60 * sample_rate / hop / 180))
    maximum = min(len(autocorr) - 2, int(60 * sample_rate / hop / 68))
    if maximum <= minimum:
        return None, []
    lag = minimum + int(np.argmax(autocorr[minimum:maximum+1]))
    # A second beat can align better with an integer hop at fast tempos. Prefer
    # the fundamental when the half-lag has comparable support in the kick band.
    half = round(lag / 2)
    if half >= minimum:
        half = max(range(max(minimum, half-1), min(maximum, half+1)+1), key=lambda value: autocorr[value])
        if autocorr[half] >= .35 * autocorr[lag]:
            lag = half
    # Parabolic peak interpolation removes hop quantization error.
    a, b, c = autocorr[lag-1:lag+2]
    refined = lag + float(.5 * (a-c) / (a-2*b+c)) if abs(a-2*b+c) > 1e-12 else float(lag)
    bpm = 60 * sample_rate / hop / refined
    period = 60 / bpm
    offsets = np.linspace(0, period, 100, endpoint=False)
    def phase_score(offset):
        positions = (np.arange(offset, len(low) / sample_rate, period) * sample_rate / hop).astype(int)
        return onset[np.minimum(positions, len(onset)-1)].sum()
    offset = max(offsets, key=phase_score)
    return float(bpm), np.arange(offset, len(low) / sample_rate, period).tolist()


def tempo_from_file(path: Path) -> tuple[float | None, list[float]]:
    """Tempo-only upgrade: same bounded resampling as the full feature path."""
    info = sf.info(path)
    divisor = math.gcd(info.samplerate, 11025)
    lows = []
    for audio in sf.blocks(path, blocksize=info.samplerate * 5, dtype="float64", always_2d=True):
        low = signal.resample_poly(audio.mean(axis=1), 11025 // divisor, info.samplerate // divisor)
        if len(low) < 4096:
            low = np.pad(low, (0, 4096 - len(low)))
        lows.append(low)
    return estimate_tempo(np.concatenate(lows)) if lows else (None, [])


def upgrade_tempo(path: Path, features: dict, *, verify_hash: bool = True) -> dict:
    """Only unresolved low tempi can change under the revised half-lag rule."""
    if features.get("version") == VERSION:
        return features
    if features.get("version") != "analysis-v2":
        raise ValueError("only compatible analysis-v2 features can be upgraded")
    if features.get("bpm") is not None and features["bpm"] <= 95:
        if verify_hash and file_hash(path) != features["source_hash"]:
            raise ValueError("source changed since analysis; recompute full features")
        features = {**features, "bpm": None, "beat_positions": []}
        features["bpm"], features["beat_positions"] = tempo_from_file(path)
    return {**features, "version": VERSION, "upgraded_from": "analysis-v2"}


def combine_stem_features(features: dict[str, dict]) -> dict:
    """Harmonic accompaniment identifies key; percussion identifies pulse.

    No ground-truth labels enter this function. Retain mix-only estimates for
    evaluation: monophonic bass and percussion cannot reliably identify mode.
    """
    key_source = next((name for name in ("other", "mix", "vocals", "bass")
                       if features.get(name, {}).get("key") is not None), None)
    tempo_source = next((name for name in ("drums", "mix", "bass", "vocals")
                         if features.get(name, {}).get("bpm") is not None), None)
    synthetic = True if any(value.get("synthetic") is True for value in features.values()) else (
        False if all(value.get("synthetic") is False for value in features.values()) else None)
    augmented = True if any(value.get("augmented") is True for value in features.values()) else (
        False if all(value.get("augmented") is False for value in features.values()) else None)
    return {"version": "track-analysis-v1", "synthetic": synthetic, "augmented": augmented,
            "real": bool(features) and all(value.get("real") is True for value in features.values()) and synthetic is False and augmented is False,
            "key": features[key_source]["key"] if key_source else None,
            "key_source": key_source, "bpm": features[tempo_source]["bpm"] if tempo_source else None,
            "tempo_source": tempo_source,
            "beat_positions": features[tempo_source]["beat_positions"] if tempo_source else [],
            "lufs": features.get("mix", {}).get("lufs"),
            "mix_only_key": features.get("mix", {}).get("key"),
            "mix_only_bpm": features.get("mix", {}).get("bpm")}


def with_provenance(features: dict, provenance: dict | None) -> dict:
    """Unknown origin stays unknown; only the source adapter classifies audio."""
    values = {name: provenance.get(name) if provenance else features.get(name) for name in ("synthetic", "augmented", "real")}
    return {**features, **values, "windows": [{**window, **values} for window in features.get("windows", [])]}


def analyze_file(path: str | Path, output: Path | None = None, *, force: bool = False,
                 provenance: dict | None = None) -> dict:
    path = Path(path)
    source_hash = file_hash(path)
    if output is not None and output.exists() and not force:
        cached = json.loads(output.read_text(encoding="utf-8"))
        if cached.get("source_hash") == source_hash:
            if cached.get("version") == VERSION:
                if provenance is not None:
                    cached = with_provenance(cached, provenance)
                    atomic_json(output, cached)
                return cached
            if cached.get("version") == "analysis-v2":
                cached = with_provenance(upgrade_tempo(path, cached, verify_hash=False), provenance)
                atomic_json(output, cached)
                return cached
    # scipy returns an actual memory map for our PCM16 corpus. Compressed inputs
    # use SoundFile's bounded seek/read adapter instead of pretending to be mmap.
    try:
        sr, mapped = wavfile.read(path, mmap=True)
        mapped = mapped[:, None] if mapped.ndim == 1 else mapped
        frames = len(mapped)
        def read(start, stop):
            block = mapped[start:stop].astype(np.float64)
            if np.issubdtype(mapped.dtype, np.integer):
                if mapped.dtype == np.uint8:
                    return (block - 128) / 128
                block /= 2 ** (np.iinfo(mapped.dtype).bits - 1)
            return block
    except (ValueError, OSError):
        info = sf.info(path)
        sr, frames = info.samplerate, info.frames
        def read(start, stop):
            return sf.read(path, start=start, stop=stop, dtype="float64", always_2d=True)[0]
    windows, lows, chroma = [], [], np.zeros(12)
    # pyloudnorm computes proper gated integrated loudness for each analysis
    # window. Track integrated LUFS is separately evaluated below with BS.1770
    # gating over continuously K-weighted 400 ms blocks.
    meter = pyln.Meter(sr)
    filter_states = {}
    k_energy_blocks = []
    weighted_tail = np.empty((0, mapped.shape[1] if 'mapped' in locals() else info.channels))
    block_length, step = round(.4 * sr), round(.1 * sr)
    for start in range(0, frames, sr * 5):
        audio = read(start, min(start + sr * 5, frames))
        features, low = _features(audio, sr)
        chroma += features["chroma"]
        lows.append(low)
        features.update({"start_seconds": start / sr, "duration_seconds": len(audio) / sr})
        weighted = audio.copy()
        for name, filt in meter._filters.items():
            state = filter_states.get(name, np.zeros((max(len(filt.a), len(filt.b))-1, audio.shape[1])))
            weighted, state = signal.lfilter(filt.b, filt.a, weighted, axis=0, zi=state)
            filter_states[name] = state
        weighted = np.concatenate((weighted_tail, weighted))
        starts = np.arange(0, len(weighted) - block_length + 1, step)
        cumulative = np.concatenate((np.zeros((1, weighted.shape[1])), np.cumsum(weighted**2, axis=0)))
        energies = (cumulative[starts + block_length] - cumulative[starts]) / block_length
        k_energy_blocks.extend(energies)
        features["lufs"] = _gated_loudness(energies)
        windows.append(features)
        last = int(starts[-1] + step) if len(starts) else 0
        weighted_tail = weighted[last:]
    energies = np.asarray(k_energy_blocks)
    loudness = _gated_loudness(energies)
    key, confidence = estimate_key(chroma)
    bpm, beats = estimate_tempo(np.concatenate(lows)) if lows else (None, [])
    result = {"version": VERSION, "source_hash": source_hash, "duration_seconds": frames / sr,
              "sample_rate": sr, "bpm": bpm, "beat_positions": beats, "key": key,
              "key_confidence": confidence, "lufs": loudness, "windows": windows,
              "energy_curve": [window["rms"] for window in windows]}
    result = with_provenance(result, provenance)
    if output is not None:
        guarded(output.parent)
        atomic_json(output, result)
    return result


def _job(arguments):
    path, output, force, *extra = arguments
    return analyze_file(path, output, force=force, provenance=extra[0] if extra else None)


def enqueue_analysis(queue, rows: list[dict], destination: Path) -> int:
    """Use the JobQueue interface; keys pin both audio content and algorithm."""
    count = 0
    for row in rows:
        for stem, path in row["paths"].items():
            payload = {"path": path, "output": str(destination / row["track_id"] / f"{stem}.json"),
                       "synthetic": row.get("synthetic"), "augmented": row.get("augmented"), "real": row.get("real")}
            count += queue.enqueue("analysis", VERSION + ":" + row["hashes"][stem] + ":" + row["track_id"] + ":" + stem, payload)
    return count


def drain_analysis(queue, workers: int | None = None, owner: str = "gpt-sol") -> dict:
    """Lease/extend/ack only after atomic output. Expired work can be resumed."""
    workers = configured_workers(workers)
    completed, failed = 0, 0
    with process_pool(workers) as pool:
        pending = {}
        while True:
            for job in queue.lease("analysis", owner, n=workers - len(pending), lease_s=120):
                payload = job.payload
                provenance = {name: payload.get(name) for name in ("synthetic", "augmented", "real")}
                pending[pool.submit(_job, (payload["path"], Path(payload["output"]), False, provenance))] = job
            if not pending:
                break
            done, _ = wait(pending, timeout=30, return_when=FIRST_COMPLETED)
            for future in pending:
                if future not in done:
                    queue.extend(pending[future].id, lease_s=120)
            for future in done:
                job = pending.pop(future)
                try:
                    result = future.result()
                    queue.ack(job.id, {"source_hash": result["source_hash"], "version": VERSION,
                                       "output": job.payload["output"],
                                       "synthetic": job.payload.get("synthetic"),
                                       "augmented": job.payload.get("augmented"), "real": job.payload.get("real")})
                    completed += 1
                except Exception as exc:
                    queue.fail(job.id, str(exc), retry=True)
                    failed += 1
    return {"completed": completed, "failed_attempts": failed, "counts": queue.counts("analysis")}


def analyze_corpus(corpus: Path, destination: Path, workers: int | None = None, force: bool = False) -> dict:
    import pyarrow.parquet as pq
    rows = pq.read_table(corpus / "manifest.parquet").to_pylist()
    jobs = [(row, name, path) for row in rows for name, path in row["paths"].items()]
    destination.mkdir(parents=True, exist_ok=True)
    started, completed, errors = time.perf_counter(), 0, []
    scores = []
    with LaneMonitor() as monitor, process_pool(configured_workers(workers)) as pool:
        pending, iterator = {}, iter(jobs)
        while True:
            while len(pending) < configured_workers(workers) * 2:
                item = next(iterator, None)
                if item is None:
                    break
                row, name, path = item
                output = destination / row["track_id"] / f"{name}.json"
                provenance = {flag: row.get(flag) for flag in ("synthetic", "augmented", "real")}
                pending[pool.submit(_job, (path, output, force, provenance))] = (row, name)
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                row, name = pending.pop(future)
                try:
                    result = future.result()
                except Exception as exc:
                    errors.append({"track_id": row["track_id"], "stem": name, "error": str(exc)})
                    continue
                completed += 1
                if name == "mix":
                    scores.append({"track_id": row["track_id"], "bpm_error": abs(result["bpm"] - row["bpm"]) if result["bpm"] else None,
                                   "key_correct": result["key"] == row["key"]})
                if completed % 25 == 0:
                    print(json.dumps({"stage": "analysis", "completed": completed, "target": len(jobs)}), flush=True)
    elapsed = time.perf_counter() - started
    mix_scores = scores
    scores = []
    for row in rows:
        features = {}
        for name in row["paths"]:
            path = destination / row["track_id"] / f"{name}.json"
            if path.exists():
                features[name] = json.loads(path.read_text(encoding="utf-8"))
        if features:
            combined = combine_stem_features(features)
            atomic_json(destination / row["track_id"] / "track.json", combined)
            scores.append({"track_id": row["track_id"],
                           "bpm_error": abs(combined["bpm"] - row["bpm"]) if combined["bpm"] else None,
                           "key_correct": combined["key"] == row["key"]})
    elapsed = time.perf_counter() - started
    bpm_errors = [row["bpm_error"] for row in scores if row["bpm_error"] is not None]
    result = {"stage": "analysis", "items": completed, "tracks": len(scores), "wall_seconds": elapsed,
              "items_per_minute": completed * 60 / elapsed, "tracks_per_minute": len(scores) * 60 / elapsed,
              "mean_bpm_error": float(np.mean(bpm_errors)) if bpm_errors else None,
              "key_accuracy": float(np.mean([row["key_correct"] for row in scores])) if scores else None,
              "mix_key_accuracy": float(np.mean([row["key_correct"] for row in mix_scores])) if mix_scores else None,
              "mix_mean_bpm_error": float(np.mean([row["bpm_error"] for row in mix_scores if row["bpm_error"] is not None])) if mix_scores else None,
              "accuracy_method": "key from harmonic other stem, tempo from drums; mix-only estimates retained separately",
              "errors": errors, "scores": scores, **monitor.summary()}
    atomic_json(destination / "benchmark.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(os.environ.get("REMIXER_DATA_DIR", "data"))
    parser.add_argument("--corpus", type=Path, default=root / "corpus")
    parser.add_argument("--output", type=Path, default=root / "analysis")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(json.dumps(analyze_corpus(args.corpus, args.output, args.workers, args.force), indent=2))


if __name__ == "__main__":
    main()

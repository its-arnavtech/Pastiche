"""Feeder pipeline: decode tracks on the GPU-feeder cores into pinned memory, ahead of the GPU.

Threads, not processes: libsndfile reads and the int16 copy release the GIL, and the decoded
arrays never cross a process boundary (no 30-60 MB pickles per track).
"""
from __future__ import annotations

import logging
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

import numpy as np

log = logging.getLogger("remixer.gpu.prefetch")


@dataclass
class Loaded:
    item: Any                 # whatever the caller attached (job, track row)
    audio: Any                # torch int16 tensor (channels, frames), pinned
    sample_rate: int
    frames: int
    error: str | None = None
    meta: dict = field(default_factory=dict)


def decode(path: Path, target_sr: int, channels: int = 2) -> tuple[np.ndarray, int]:
    """Read audio as int16 (frames, channels). Resamples with ffmpeg only when needed."""
    import soundfile as sf

    info = sf.info(str(path))
    if info.samplerate == target_sr and info.format in ("WAV", "FLAC", "AIFF", "OGG"):
        data = sf.read(str(path), dtype="int16", always_2d=True)[0]
    else:
        import subprocess

        cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", str(channels),
               "-ar", str(target_sr), "-"]
        raw = subprocess.run(cmd, capture_output=True, check=True).stdout
        data = np.frombuffer(raw, dtype=np.int16).reshape(-1, channels)
    if data.shape[1] == 1:
        data = np.repeat(data, channels, axis=1)
    elif data.shape[1] > channels:
        data = data[:, :channels]
    return data, target_sr


class Prefetcher:
    """Iterate Loaded tracks; keeps up to `depth` decoded tracks ready in pinned memory."""

    def __init__(self, items: Iterable[tuple[Any, Path]], target_sr: int, workers: int = 4, depth: int = 4,
                 pin: bool = True):
        self.items = iter(items)
        self.sr = target_sr
        self.pin = pin
        self.q: queue.Queue = queue.Queue(maxsize=max(1, depth))
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="feeder")
        self.stats = {"decoded": 0, "errors": 0, "wait_s": 0.0, "empty_s": 0.0}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="prefetch", daemon=True)
        self._thread.start()

    def _load(self, item, path) -> Loaded:
        import torch

        try:
            data, sr = decode(Path(path), self.sr)
            t = torch.from_numpy(np.ascontiguousarray(data.T))
            if self.pin:
                t = t.pin_memory()
            return Loaded(item=item, audio=t, sample_rate=sr, frames=data.shape[0])
        except Exception as e:  # a bad file must not stall the GPU
            log.warning("decode failed for %s: %s", path, e)
            return Loaded(item=item, audio=None, sample_rate=self.sr, frames=0, error=repr(e))

    def _run(self) -> None:
        # Keep `workers` decodes in flight; deliver in submission order.
        inflight: list = []
        try:
            for item, path in self.items:
                if self._stop.is_set():
                    break
                inflight.append(self.pool.submit(self._load, item, path))
                if len(inflight) >= self.pool._max_workers:
                    self._put(inflight.pop(0).result())
            for f in inflight:
                self._put(f.result())
        finally:
            self.q.put(None)

    def _put(self, loaded: Loaded) -> None:
        self.stats["decoded"] += 1
        self.stats["errors"] += loaded.error is not None
        while not self._stop.is_set():
            try:
                self.q.put(loaded, timeout=0.5)
                return
            except queue.Full:
                continue

    def __iter__(self) -> Iterator[Loaded]:
        import time

        while True:
            t, empty = time.perf_counter(), self.q.empty()
            x = self.q.get()
            self.stats["wait_s"] += time.perf_counter() - t
            if empty:  # the GPU asked for work and the feeders had none ready
                self.stats["empty_s"] += time.perf_counter() - t
            if x is None:
                return
            yield x

    def close(self) -> None:
        self._stop.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self._thread.join(timeout=30)  # so callers can safely release whatever it pulled from `items`

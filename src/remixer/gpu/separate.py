"""Demucs separation worker (GPU lane).

Tracks are cut into model-length segments (7.8 s for htdemucs, 25% overlap) and segments from
consecutive tracks are packed into one batch, so the batch size is set by VRAM, not by track
count. Overlap-add happens on the GPU per track; only finished int16 regions go back to the host
and are streamed to WAV by a writer thread. Stems are keyed by (track content hash, model version)
and a job is acked only after its stems are on disk, so a kill loses at most the in-flight track.

Heavy mode (htdemucs_ft bag + extra shifts) is a pure load generator: outputs are discarded.
"""
from __future__ import annotations

import json
import logging
import math
import os
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

log = logging.getLogger("remixer.gpu.separate")
OVERLAP = 0.25
STARVED_UTIL = 80  # percent; below this with an empty feeder queue counts as starvation


def model_version(name: str) -> str:
    import demucs

    return f"{name}@demucs-{demucs.__version__}"


class DemucsRunner:
    def __init__(self, name: str = "htdemucs", fp16: bool = True, device: str = "cuda", shifts: int = 1):
        import torch
        from demucs.pretrained import get_model

        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        bag = get_model(name)
        self.name = name
        self.version = model_version(name)
        self.models = [m.to(device).eval() for m in bag.models]
        self.sources = list(bag.sources)
        self.sr = bag.samplerate
        self.segment = int(float(self.models[0].segment) * self.sr)
        self.stride = int(self.segment * (1 - OVERLAP))
        w = bag.weights or [[1.0] * len(self.sources)] * len(self.models)
        self.weights = [torch.tensor(x, device=device).view(1, -1, 1, 1) for x in w]
        self.total_w = sum(self.weights)
        self.fp16 = fp16
        self.device = device
        self.shifts = max(1, shifts)
        half = self.segment // 2
        tri = torch.cat([torch.arange(1, half + 1), torch.arange(self.segment - half, 0, -1)]).float()
        self.window = (tri / tri.max()).to(device)

    @property
    def passes_per_batch(self) -> int:
        return len(self.models) * self.shifts

    def __call__(self, x):
        """x: (B, 2, segment) float32 on device -> (B, S, 2, segment) float32."""
        import torch

        out = None
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16, enabled=self.fp16):
            for s in range(self.shifts):
                xs = x if s == 0 else torch.roll(x, shifts=int(s * 0.5 * self.sr / self.shifts), dims=-1)
                for m, w in zip(self.models, self.weights):
                    y = m(xs).float() * w
                    out = y if out is None else out + y
        return out / (self.total_w * self.shifts)


@dataclass
class TrackState:
    item: Any
    norm: Any            # (2, T) float32 on device, normalized
    mean: float
    std: float
    frames: int
    n_chunks: int
    acc: Any = None
    wsum: Any = None
    pos: int = 0
    received: int = 0
    tmp_paths: dict = field(default_factory=dict)
    final_paths: dict = field(default_factory=dict)


def n_chunks(frames: int, segment: int, stride: int) -> int:
    return 1 if frames <= segment else math.ceil((frames - segment) / stride) + 1


def chunk(state: TrackState, k: int, segment: int, stride: int):
    import torch.nn.functional as F

    off = k * stride
    x = state.norm[:, off:off + segment]
    return F.pad(x, (0, segment - x.shape[-1])) if x.shape[-1] < segment else x


class StemWriter(threading.Thread):
    """Streams finished regions to temp WAVs; on close renames them and reports the track done."""

    def __init__(self, sr: int, sources: list[str], done: "queue.Queue"):
        super().__init__(name="stem-writer", daemon=True)
        self.q: queue.Queue = queue.Queue(maxsize=64)
        self.sr, self.sources, self.done = sr, sources, done
        self._files: dict[int, dict] = {}
        self.bytes = 0

    def run(self) -> None:
        import soundfile as sf

        while (msg := self.q.get()) is not None:
            op, state, data = msg
            sid = id(state)
            try:
                if op == "write":
                    if sid not in self._files:
                        for p in state.tmp_paths.values():
                            p.parent.mkdir(parents=True, exist_ok=True)
                        self._files[sid] = {s: sf.SoundFile(str(state.tmp_paths[s]), "w", self.sr, 2, "PCM_16")
                                            for s in self.sources}
                    for i, s in enumerate(self.sources):
                        self._files[sid][s].write(data[i].T)
                    self.bytes += data.nbytes
                else:  # close
                    for f in self._files.pop(sid, {}).values():
                        f.close()
                    for s in self.sources:
                        os.replace(state.tmp_paths[s], state.final_paths[s])
                    self.done.put((state, None))
            except Exception as e:
                log.exception("writer failed")
                for f in self._files.pop(sid, {}).values():
                    f.close()
                self.done.put((state, repr(e)))


@dataclass
class Metrics:
    stage: str
    t0: float = field(default_factory=time.perf_counter)
    last: float = field(default_factory=time.perf_counter)
    audio_s: float = 0.0
    window_audio_s: float = 0.0
    batches: int = 0
    tracks: int = 0
    gpu_s: float = 0.0
    rows: list = field(default_factory=list)

    def add(self, audio_s: float, gpu_s: float) -> None:
        self.audio_s += audio_s
        self.window_audio_s += audio_s
        self.gpu_s += gpu_s
        self.batches += 1

    def maybe_emit(self, every_s: float, **extra) -> dict | None:
        import torch

        now = time.perf_counter()
        if now - self.last < every_s:
            return None
        row = {"ts": time.time(), "stage": self.stage, "wall_s": now - self.last,
               "audio_s": self.window_audio_s, "rate_x": self.window_audio_s / (now - self.last),
               "total_audio_s": self.audio_s, "tracks": self.tracks, "batches": self.batches,
               "vram_peak_gib": torch.cuda.max_memory_allocated() / 2**30, **extra}
        self.rows.append(row)
        self.last, self.window_audio_s = now, 0.0
        log.info("%s: %.1fx realtime, %d tracks, batch %s, prefetch wait %.1fs", self.stage, row["rate_x"],
                 self.tracks, extra.get("batch"), extra.get("prefetch_wait_s", 0))
        return row


class Separator:
    def __init__(self, adapters, model: str | None = None, heavy: bool = False, shifts: int | None = None,
                 batch: int | None = None, feeders: int | None = None):
        import torch

        gcfg = adapters.profile["gpu"]
        self.a = adapters
        self.heavy = heavy
        name = model or (gcfg["heavy_model"] if heavy else gcfg["separation_model"])
        self.runner = DemucsRunner(name, fp16=gcfg["fp16"], shifts=(shifts or gcfg["heavy_shifts"]) if heavy else 1)
        torch.backends.cudnn.benchmark = True
        from remixer.gpu.vram import BatchSizer

        key = f"demucs:{self.runner.version}:fp16={gcfg['fp16']}:shifts={self.runner.shifts}"
        self.sizer = BatchSizer(adapters.profile.data_dir / "state" / "gpu_sizes.json", key)
        self.fixed_batch = batch
        self.feeders = feeders or adapters.profile.resources.gpu_feeders
        self.stems_root = adapters.profile.data_dir / "stems"
        self._leased: dict[int, Any] = {}

    # ---- sizing
    def batch_size(self) -> int:
        if self.fixed_batch:
            return self.fixed_batch
        import torch

        from remixer.gpu.vram import measure_peak

        L = self.runner.segment

        def peak(b):
            x = torch.randn(b, 2, L, device="cuda")
            return measure_peak(lambda: self.runner(x))

        def seconds(b, iters=3):
            x = torch.randn(b, 2, L, device="cuda")
            self.runner(x)  # warm-up (cudnn autotune for this shape)
            torch.cuda.synchronize()
            t = time.perf_counter()
            for _ in range(iters):
                self.runner(x)
            torch.cuda.synchronize()
            return (time.perf_counter() - t) / iters

        bench = torch.backends.cudnn.benchmark
        torch.backends.cudnn.benchmark = False  # autotune workspaces would inflate the memory fit
        try:
            return self.sizer.calibrate(peak, seconds)
        finally:
            torch.backends.cudnn.benchmark = bench
            torch.cuda.empty_cache()

    # ---- sources
    def leased(self, limit: int | None = None, lease_s: float = 1800) -> Iterator[tuple[Any, Path]]:
        q = self.a.jobs
        kind = f"separate:{self.runner.name}"
        n = 0
        while limit is None or n < limit:
            jobs = q.lease(kind, owner=f"opus-cc-gpu-{os.getpid()}", n=min(4, limit - n) if limit else 4,
                           lease_s=lease_s)
            if not jobs:
                return
            for j in jobs:
                n += 1
                self._leased[j.id] = j
                yield j, Path(j.payload["path"])

    def release_unfinished(self) -> int:
        """Return leased-but-unprocessed jobs to the queue (e.g. after --duration stops a run)."""
        ids = list(self._leased)
        for jid in ids:
            self.a.jobs.release(jid)
        self._leased.clear()
        return len(ids)

    def corpus_cycle(self, seed: int = 0) -> Iterator[tuple[Any, Path]]:
        rows = self.a.catalog.query("SELECT track_id, source_path FROM tracks ORDER BY track_id")
        if not rows:
            raise SystemExit("catalog has no tracks: run `remixer ingest` first")
        while True:
            for r in rows:
                yield r, Path(r["source_path"])

    def _check_starvation(self, row: dict, empty_s: float) -> None:
        """Starvation = GPU below 80 % utilization while the feeder queue ran empty in this window."""
        h = getattr(self.a.compute, "_h", None)
        try:
            import pynvml

            row["gpu_util"] = pynvml.nvmlDeviceGetUtilizationRates(h).gpu if h is not None else None
        except Exception:  # NVML reads fail transiently on Optimus laptops
            row["gpu_util"] = None
        if row["gpu_util"] is not None and row["gpu_util"] < STARVED_UTIL and empty_s > 0:
            log.warning("starvation: GPU %d%% while feeders left the queue empty for %.2fs of %.1fs",
                        row["gpu_util"], empty_s, row["wall_s"])
            self.a.events.append("gpu_starvation", [{"ts": row["ts"], "stage": row["stage"], "gpu_util": row["gpu_util"],
                                                      "feeder_empty_s": round(empty_s, 3), "window_s": row["wall_s"]}])

    # ---- main loop
    def run(self, items: Iterable[tuple[Any, Path]], persist: bool, duration_s: float | None = None,
            metrics_every_s: float = 5.0, guard=None) -> Metrics:
        import numpy as np
        import torch

        from remixer.gpu.prefetch import Prefetcher

        R = self.runner
        L, S = R.segment, R.stride
        B = self.batch_size()
        stage = "separate_heavy" if self.heavy else "separate"
        met = Metrics(stage)
        done_q: queue.Queue = queue.Queue()
        writer = StemWriter(R.sr, R.sources, done_q)
        if persist:
            writer.start()
        depth = max(2, math.ceil(2 * B / max(1, n_chunks(180 * R.sr, L, S))) + 1)  # >= 2 batches ahead
        pre = Prefetcher(items, R.sr, workers=self.feeders, depth=depth)
        tracks = iter(pre)
        pending: deque = deque()
        t_start = time.perf_counter()
        last_guard = last_empty = 0.0
        exhausted = False
        try:
            while True:
                if duration_s and time.perf_counter() - t_start >= duration_s:
                    break
                if guard is not None and time.perf_counter() - last_guard > 10:
                    last_guard = time.perf_counter()
                    guard.gate(writer=persist)
                while len(pending) < B and not exhausted:
                    loaded = next(tracks, None)
                    if loaded is None:
                        exhausted = True
                        break
                    if loaded.error:
                        self._fail(loaded.item, loaded.error)
                        continue
                    st = self._new_state(loaded, persist)
                    if st is None:
                        continue
                    pending.extend((st, k) for k in range(st.n_chunks))
                if not pending:
                    break
                batch = [pending.popleft() for _ in range(min(B, len(pending)))]
                x = torch.stack([chunk(st, k, L, S) for st, k in batch])
                t = time.perf_counter()
                try:
                    y = R(x)
                except torch.OutOfMemoryError:
                    del x
                    torch.cuda.empty_cache()
                    B = self.sizer.on_oom()
                    pending.extendleft(reversed(batch))
                    continue
                for i, (st, k) in enumerate(batch):
                    out = self._accumulate(st, k, y[i])
                    if persist and out is not None:
                        writer.q.put(("write", st, out))
                    if st.received == st.n_chunks:
                        st.norm = st.acc = st.wsum = None
                        if persist:
                            writer.q.put(("close", st, None))
                        else:
                            met.tracks += 1
                del y
                met.add(len(batch) * S / R.sr, time.perf_counter() - t)
                self._drain(done_q, met)
                if row := met.maybe_emit(metrics_every_s, batch=B, prefetch_wait_s=round(pre.stats["wait_s"], 2),
                                         feeder_empty_s=round(pre.stats["empty_s"], 2),
                                         passes=R.passes_per_batch, model=R.version, write_mb=writer.bytes / 1e6):
                    self._check_starvation(row, pre.stats["empty_s"] - last_empty)
                    last_empty = pre.stats["empty_s"]
                    self.a.events.append("stage_metrics", [row])
        finally:
            pre.close()
            if persist:
                writer.q.put(None)
                writer.join()
                self._drain(done_q, met)
                self.release_unfinished()
        return met

    def _new_state(self, loaded, persist: bool) -> TrackState | None:
        import torch

        R = self.runner
        track_id = self._track_id(loaded.item)
        final = {s: self.stems_root / track_id[:2] / track_id / R.version.replace("@", "_") / f"{s}.wav"
                 for s in R.sources}
        if persist and all(p.exists() for p in final.values()):
            self._ack(loaded.item, cached=True)
            return None
        audio = loaded.audio.to(R.device, non_blocking=True).float() / 32768.0
        ref = audio.mean(0)
        mean, std = ref.mean().item(), ref.std().item() or 1.0
        st = TrackState(item=loaded.item, norm=(audio - mean) / std, mean=mean, std=std, frames=loaded.frames,
                        n_chunks=n_chunks(loaded.frames, R.segment, R.stride),
                        final_paths=final,
                        tmp_paths={s: p.with_suffix(f".{os.getpid()}.partial.wav") for s, p in final.items()})
        st.acc = torch.zeros(len(R.sources), 2, R.segment, device=R.device)
        st.wsum = torch.zeros(R.segment, device=R.device)
        return st

    def _accumulate(self, st: TrackState, k: int, y):
        """Overlap-add chunk k; return the finished int16 region (S, 2, n) as numpy, or None."""
        import torch

        R = self.runner
        S, L = R.stride, R.segment
        st.acc += y * R.window
        st.wsum += R.window
        st.received += 1
        off = k * S
        last = st.received == st.n_chunks
        n = min(st.frames - off, L if last else S)
        if n <= 0:
            return None
        region = st.acc[..., :n] / st.wsum[:n].clamp_min(1e-8) * st.std + st.mean
        out = (region * 32767.0).clamp_(-32768, 32767).to(torch.int16).cpu().numpy()
        if not last:
            st.acc = torch.roll(st.acc, -S, dims=-1)
            st.acc[..., L - S:] = 0
            st.wsum = torch.roll(st.wsum, -S)
            st.wsum[L - S:] = 0
        return out

    # ---- bookkeeping
    @staticmethod
    def _track_id(item) -> str:
        return item.payload["track_id"] if hasattr(item, "payload") else item["track_id"]

    def _drain(self, done_q, met: Metrics) -> None:
        while True:
            try:
                st, err = done_q.get_nowait()
            except queue.Empty:
                return
            if err:
                self._fail(st.item, err)
                continue
            met.tracks += 1
            self._register(st)
            self._ack(st.item)

    def _register(self, st: TrackState) -> None:
        import hashlib

        R = self.runner
        tid = self._track_id(st.item)
        root = self.a.profile.data_dir
        for s, p in st.final_paths.items():
            sid = hashlib.sha256(f"{tid}|{R.version}|{s}".encode()).hexdigest()
            self.a.catalog.upsert("stems", {
                "stem_id": sid, "track_id": tid, "stem_name": s, "model": R.name, "model_version": R.version,
                "blob_key": p.relative_to(root).as_posix(), "duration_s": st.frames / R.sr,
                "synthetic": int(bool(self._synthetic(tid)))}, key=["stem_id"])

    def _synthetic(self, tid: str) -> bool:
        row = self.a.catalog.get("tracks", track_id=tid)
        return bool(row and row.get("synthetic"))

    def _ack(self, item, cached: bool = False) -> None:
        if hasattr(item, "id"):
            self._leased.pop(item.id, None)
            self.a.jobs.ack(item.id, {"cached": cached})

    def _fail(self, item, err: str) -> None:
        if hasattr(item, "id"):
            self._leased.pop(item.id, None)
            self.a.jobs.fail(item.id, err)
        log.warning("separation failed: %s", err)


def summary(met: Metrics) -> dict:
    wall = time.perf_counter() - met.t0
    # skip warm-up (first batches, cudnn autotune): windows ending in the first 15 s after the first one
    first = met.rows[0]["ts"] if met.rows else 0
    steady = [r for r in met.rows if r["ts"] - first >= 15] or met.rows[1:] or met.rows
    s_audio, s_wall = sum(r["audio_s"] for r in steady), sum(r["wall_s"] for r in steady)
    passes = steady[-1]["passes"] if steady else 1
    return {"stage": met.stage, "tracks": met.tracks, "audio_s": round(met.audio_s, 1),
            "wall_s": round(wall, 1), "rate_x": round(met.audio_s / wall, 2) if wall else 0,
            "steady_rate_x": round(s_audio / s_wall, 2) if s_wall else 0,
            "model_rate_x": round(passes * s_audio / s_wall, 2) if s_wall else 0,
            "batches": met.batches}


if __name__ == "__main__":
    print(json.dumps({"hint": "use `remixer separate`"}))

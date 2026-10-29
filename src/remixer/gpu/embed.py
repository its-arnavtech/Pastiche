"""CLAP embedding worker (GPU lane): one 512-d vector per 5-second window of every stem, plus a
per-stem vector (normalized mean of its windows).

Everything after decode happens on the GPU: 44.1 -> 48 kHz resampling (julius), the CLAP log-mel
front end (matches transformers' ClapFeatureExtractor, rand_trunc/repeatpad path, checked in
tests), and the HTSAT audio tower in fp16. Windows from many stems share one batch, sized by
the same VRAM calibration as separation.

Checkpoint per stem: vectors to <data>/embeddings/<model>/<stem_id>.npy, rows to the catalog,
then ack. The hnswlib index is derived state and can be rebuilt from the .npy files.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import numpy as np

log = logging.getLogger("remixer.gpu.embed")
CLAP_SR = 48_000
CLAP_LEN = 480_000  # 10 s model input; 5 s windows are repeat-padded to it
N_FFT, HOP = 1024, 480


def model_version(name: str) -> str:
    import transformers

    return f"{name}@transformers-{transformers.__version__}-logmel-f32-v2"


class ClapFrontEnd:
    """GPU log-mel identical to ClapFeatureExtractor(truncation='rand_trunc', padding='repeatpad')."""

    def __init__(self, mel_filters: np.ndarray, device: str):
        import torch

        self.fb = torch.from_numpy(np.asarray(mel_filters, dtype=np.float32)).to(device)  # (513, 64)
        self.window = torch.hann_window(N_FFT, periodic=True, device=device)

    def __call__(self, wave):
        """wave: (B, CLAP_LEN) float32 -> (B, 1, frames, 64)."""
        import torch

        # The 1e-10 log floor underflows to zero in fp16. Keep the complete
        # power/mel/log front end in fp32 even inside encoder autocast.
        with torch.autocast(wave.device.type, enabled=False):
            spec = torch.stft(wave.float(), N_FFT, HOP, window=self.window.float(), center=True, pad_mode="reflect",
                              return_complex=True)
            mel = torch.einsum("bft,fm->bmt", spec.abs().pow(2), self.fb.float())
            db = 10.0 * torch.log10(mel.clamp_min(1e-10))
        return db.transpose(1, 2).unsqueeze(1)


def repeat_pad(x, length: int = CLAP_LEN):
    """(B, n) -> (B, length): tile int(length / n) times, then zero-pad (CLAP 'repeatpad')."""
    import torch.nn.functional as F

    n = x.shape[-1]
    if n >= length:
        return x[..., :length]
    reps = length // n
    return F.pad(x.repeat(1, reps), (0, length - n * reps))


@dataclass
class StemState:
    item: Any
    stem_id: str
    windows: list                     # list of (start_ms, end_ms)
    vectors: list = field(default_factory=list)
    synthetic: bool = True


class Embedder:
    def __init__(self, adapters, model: str | None = None, batch: int | None = None, window_s: float | None = None,
                 feeders: int | None = None):
        import torch
        from transformers import ClapFeatureExtractor, ClapModel

        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        g = adapters.profile["gpu"]
        self.a = adapters
        self.name = model or g["embedding_model"]
        self.version = model_version(self.name)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.fp16 = bool(g["fp16"]) and self.device == "cuda"
        fe = ClapFeatureExtractor.from_pretrained(self.name)
        self.front = ClapFrontEnd(fe.mel_filters_slaney, self.device)
        clap = ClapModel.from_pretrained(self.name)
        self.audio = clap.audio_model.to(self.device).eval()
        self.proj = clap.audio_projection.to(self.device).eval()
        del clap
        self.dim = self.proj.linear2.out_features if hasattr(self.proj, "linear2") else 512
        self.window_s = window_s or g["window_s"]
        self.win = int(self.window_s * CLAP_SR)
        self.fixed_batch = batch
        self.feeders = feeders or adapters.profile.resources.gpu_feeders
        from remixer.gpu.vram import BatchSizer

        self.sizer = BatchSizer(adapters.profile.data_dir / "state" / "gpu_sizes.json",
                                f"clap:{self.version}:fp16={self.fp16}:win={self.window_s}")
        self.vec_root = adapters.profile.data_dir / "embeddings" / self.version.replace("@", "_").replace("/", "_")
        self._leased: dict[int, Any] = {}

    def embed(self, wave):
        """(B, CLAP_LEN) float32 on device -> (B, dim) L2-normalized float32."""
        import torch
        import torch.nn.functional as F

        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16, enabled=self.fp16):
            feats = self.front(wave)
            pooled = self.audio(input_features=feats).pooler_output
            z = self.proj(pooled)
        normalized = F.normalize(z.float(), dim=-1)
        if not torch.isfinite(normalized).all():
            raise FloatingPointError("CLAP produced nonfinite embeddings; no checkpoint may be committed")
        return normalized

    def batch_size(self) -> int:
        if self.fixed_batch:
            return self.fixed_batch
        import torch

        from remixer.gpu.vram import measure_peak

        def peak(b):
            x = torch.randn(b, CLAP_LEN, device=self.device) * 0.1
            return measure_peak(lambda: self.embed(x))

        def seconds(b, iters=3):
            x = torch.randn(b, CLAP_LEN, device=self.device) * 0.1
            self.embed(x)
            torch.cuda.synchronize()
            t = time.perf_counter()
            for _ in range(iters):
                self.embed(x)
            torch.cuda.synchronize()
            return (time.perf_counter() - t) / iters

        self.sizer.max_batch = 256
        return self.sizer.calibrate(peak, seconds)

    # ---- sources
    def enqueue_missing(self) -> int:
        rows = self.a.catalog.query(
            "SELECT s.stem_id, s.blob_key, s.synthetic FROM stems s LEFT JOIN embeddings e "
            "ON e.owner_id = s.stem_id AND e.model_version = ? WHERE e.row_id IS NULL", (self.version,))
        root = self.a.profile.data_dir
        items = [(f"{r['stem_id']}|{self.version}", {"stem_id": r["stem_id"], "path": str(root / r["blob_key"]),
                                                    "synthetic": r["synthetic"]}) for r in rows]
        return self.a.jobs.enqueue_many(f"embed:{self.name}", items)

    def leased(self, limit: int | None = None) -> Iterator[tuple[Any, Path]]:
        n = 0
        while limit is None or n < limit:
            jobs = self.a.jobs.lease(f"embed:{self.name}", owner=f"opus-cc-embed-{os.getpid()}", n=8, lease_s=1800)
            if not jobs:
                return
            for j in jobs:
                n += 1
                self._leased[j.id] = j
                yield j, Path(j.payload["path"])

    def stems_cycle(self) -> Iterator[tuple[Any, Path]]:
        root = self.a.profile.data_dir
        rows = self.a.catalog.query("SELECT stem_id, blob_key, synthetic FROM stems ORDER BY stem_id")
        if not rows:
            raise SystemExit("no stems in the catalog: run `remixer separate` first")
        while True:
            for r in rows:
                yield r, root / r["blob_key"]

    # ---- main loop
    def run(self, items, persist: bool, duration_s: float | None = None, guard=None, metrics_every_s: float = 5.0):
        import julius
        import torch

        from remixer.gpu.prefetch import Prefetcher
        from remixer.gpu.separate import Metrics

        B = self.batch_size()
        met = Metrics("embed")
        pre = Prefetcher(items, 44_100, workers=self.feeders, depth=max(4, B // 30 + 2))
        it = iter(pre)
        pending: deque = deque()  # (state, window index, tensor (win,))
        t0, last_guard, exhausted = time.perf_counter(), 0.0, False
        windows_done = 0
        try:
            while True:
                if duration_s and time.perf_counter() - t0 >= duration_s:
                    break
                if guard is not None and time.perf_counter() - last_guard > 10:
                    last_guard = time.perf_counter()
                    guard.gate(writer=persist)
                while len(pending) < B and not exhausted:
                    loaded = next(it, None)
                    if loaded is None:
                        exhausted = True
                        break
                    if loaded.error:
                        self._finish(loaded.item, None, err=loaded.error)
                        continue
                    st = self._state(loaded.item, loaded.frames, loaded.sample_rate)
                    if persist and (self.vec_root / f"{st.stem_id}.npy").exists():
                        self._finish(loaded.item, st, cached=True)
                        continue
                    x = loaded.audio.to(self.device, non_blocking=True).float().mean(0) / 32768.0
                    if loaded.sample_rate != CLAP_SR:
                        x = julius.resample_frac(x, loaded.sample_rate, CLAP_SR)
                    for i, (a, b) in enumerate(st.windows):
                        seg = x[a * CLAP_SR // 1000: b * CLAP_SR // 1000]
                        pending.append((st, i, seg))
                    if not st.windows:
                        self._finish(loaded.item, st)
                if not pending:
                    break
                batch = [pending.popleft() for _ in range(min(B, len(pending)))]
                wave = torch.stack([repeat_pad(seg[None])[0] for _, _, seg in batch])
                try:
                    z = self.embed(wave).cpu().numpy()
                except torch.OutOfMemoryError:
                    torch.cuda.empty_cache()
                    B = self.sizer.on_oom()
                    pending.extendleft(reversed(batch))
                    continue
                for (st, i, _), v in zip(batch, z):
                    st.vectors.append((i, v))
                    if len(st.vectors) == len(st.windows):
                        if persist:
                            self._finish(st.item, st)
                        met.tracks += 1
                windows_done += len(batch)
                met.add(len(batch) * self.window_s, 0.0)
                if row := met.maybe_emit(metrics_every_s, batch=B, windows=windows_done, model=self.version,
                                         prefetch_wait_s=round(pre.stats["wait_s"], 2), passes=1):
                    row["windows_per_s"] = row["audio_s"] / self.window_s / row["wall_s"]
                    self.a.events.append("stage_metrics", [row])
        finally:
            pre.close()
            for jid in list(self._leased):
                self.a.jobs.release(jid)
            self._leased.clear()
        met.windows = windows_done
        return met

    def _state(self, item, frames: int, sr: int) -> StemState:
        stem_id = item.payload["stem_id"] if hasattr(item, "payload") else item["stem_id"]
        syn = item.payload.get("synthetic", 1) if hasattr(item, "payload") else item.get("synthetic", 1)
        dur_ms = int(frames * 1000 / sr)
        step = int(self.window_s * 1000)
        wins = [(s, min(s + step, dur_ms)) for s in range(0, dur_ms, step) if min(s + step, dur_ms) - s >= 1000]
        return StemState(item=item, stem_id=stem_id, windows=wins, synthetic=bool(syn))

    def _finish(self, item, st: StemState | None, cached: bool = False, err: str | None = None) -> None:
        if err is not None or st is None:
            if hasattr(item, "id"):
                self._leased.pop(item.id, None)
                self.a.jobs.fail(item.id, err or "no state")
            return
        if cached and not self.a.catalog.query(
                "SELECT 1 FROM embeddings WHERE owner_id=? AND model_version=? AND owner_kind='stem'",
                (st.stem_id, self.version)):
            # vectors were saved by a worker that died before its catalog write: register them now (resume)
            self._register(st, np.load(self.vec_root / f"{st.stem_id}.npy"))
        if not cached and st.vectors:
            vecs = np.stack([v for _, v in sorted(st.vectors, key=lambda p: p[0])]).astype(np.float16)
            if not np.isfinite(vecs).all():
                raise FloatingPointError("refusing to persist nonfinite CLAP vectors")
            self.vec_root.mkdir(parents=True, exist_ok=True)
            tmp = self.vec_root / f".{st.stem_id}.{os.getpid()}.npy"
            np.save(tmp, vecs)
            os.replace(tmp, self.vec_root / f"{st.stem_id}.npy")
            self._register(st, vecs)
        if hasattr(item, "id"):
            self._leased.pop(item.id, None)
            self.a.jobs.ack(item.id, {"windows": len(st.windows), "cached": cached})

    def _register(self, st: StemState, vecs: np.ndarray) -> None:
        cat = self.a.catalog
        stem_vec = vecs.astype(np.float32).mean(0)
        stem_vec /= np.linalg.norm(stem_vec) or 1.0
        sid = cat.insert("embeddings", {"owner_id": st.stem_id, "owner_kind": "stem", "model": self.name,
                                        "model_version": self.version, "synthetic": int(st.synthetic)})
        ids, rows = [sid], [stem_vec]
        for (a, b), v in zip(st.windows, vecs):
            wid = hashlib.sha256(f"{st.stem_id}|{a}|{self.version}".encode()).hexdigest()
            rid = cat.insert("embeddings", {"owner_id": wid, "owner_kind": "window", "model": self.name,
                                            "model_version": self.version, "synthetic": int(st.synthetic)})
            cat.upsert("windows", {"window_id": wid, "owner_id": st.stem_id, "owner_kind": "stem", "start_ms": a,
                                   "end_ms": b, "embedding_row": rid, "model_version": self.version}, key=["window_id"])
            ids.append(rid)
            rows.append(v.astype(np.float32))
        idx = self._index()
        idx.add(ids, np.stack(rows))
        self._since_save = getattr(self, "_since_save", 0) + 1
        if self._since_save >= 25:
            idx.save()
            self._since_save = 0

    def _index(self):
        if not hasattr(self, "_idx"):
            self._idx = self.a.vector_index(f"clap-{self.version.replace('@', '_').replace('/', '_')}", self.dim)
        return self._idx

    def close(self) -> None:
        if hasattr(self, "_idx"):
            self._idx.save()


def summary(met) -> dict:
    from remixer.gpu.separate import summary as sep_summary

    s = sep_summary(met)
    s["windows"] = getattr(met, "windows", 0)
    s["windows_per_s"] = round(s["steady_rate_x"] / 5.0, 2) if s.get("steady_rate_x") else 0
    return s

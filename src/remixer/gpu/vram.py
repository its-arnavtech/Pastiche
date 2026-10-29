"""VRAM-aware batch sizing.

On Windows the NVIDIA driver's sysmem fallback can spill an oversized allocation into system RAM
instead of raising OOM, which makes a batch 10-100x slower without any error. So the batch size
is computed from measured memory (peak at B=1 and B=2, linear fit) against free VRAM with a
margin, and OOM halve-and-retry is the second line of defence. The working size is remembered
per (model, precision, segment) in <data>/state/gpu_sizes.json.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Callable

log = logging.getLogger("remixer.gpu.vram")
GiB = 2**30


def nvml_free_total() -> tuple[int, int]:
    import pynvml

    pynvml.nvmlInit()
    m = pynvml.nvmlDeviceGetMemoryInfo(pynvml.nvmlDeviceGetHandleByIndex(0))
    return m.free, m.total


class BatchSizer:
    def __init__(self, state_path: Path, key: str, margin_bytes: int = int(0.6 * GiB), max_batch: int = 64):
        self.state_path = Path(state_path)
        self.key = key
        self.margin = margin_bytes
        self.max_batch = max_batch
        self.batch: int | None = None
        self.fit: dict = {}
        try:
            entry = json.loads(self.state_path.read_text()).get(key)
        except (FileNotFoundError, json.JSONDecodeError):
            entry = None
        if entry:
            self.batch, self.fit = int(entry["batch"]), entry.get("fit", {})

    def _save(self, reason: str) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            state = json.loads(self.state_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            state = {}
        state[self.key] = {"batch": self.batch, "fit": self.fit, "reason": reason}
        tmp = self.state_path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state, indent=2))
        os.replace(tmp, self.state_path)

    def size(self, peak_for: Callable[[int], int], available: int | None = None, force: bool = False) -> int:
        """Return the batch size, measuring peak memory at B=1 and B=2 if not remembered."""
        if self.batch and not force:
            return self.batch
        import torch

        p1, p2 = peak_for(1), peak_for(2)
        per_item = max(p2 - p1, 1)
        base = max(p1 - per_item, 0)
        if available is None:
            free, _ = nvml_free_total()
            available = free + torch.cuda.memory_reserved()  # our own cache counts as used to NVML
        b = int((available - self.margin - base) // per_item)
        self.batch = max(1, min(self.max_batch, b))
        self.fit = {"base_gib": round(base / GiB, 3), "per_item_gib": round(per_item / GiB, 3),
                    "available_gib": round(available / GiB, 3), "margin_gib": round(self.margin / GiB, 3)}
        log.info("batch size %d for %s (%s)", self.batch, self.key, self.fit)
        self._save("measured")
        return self.batch

    def calibrate(self, peak_for: Callable[[int], int], seconds_for: Callable[[int], float],
                  available: int | None = None, force: bool = False) -> int:
        """Memory bound from the linear fit, then pick the fastest batch by measured items/s.

        Throughput falling as the batch grows is the signature of a sysmem spill (no OOM on
        Windows), so the search stops at the first clear drop.
        """
        if self.batch and not force:
            return self.batch
        upper = self.size(peak_for, available, force=True)
        cands = sorted({b for b in (1, 2, 4, 6, 8, 10, 12, 16, 20, 24, 32, 48, 64) if b <= upper} | {upper})
        best_b, best_rate, rates = 1, 0.0, {}
        for b in cands:
            try:
                rate = b / seconds_for(b)
            except Exception as e:  # OOM included
                log.info("calibrate: batch %d failed (%s)", b, type(e).__name__)
                break
            rates[b] = round(rate, 2)
            if rate > best_rate * 1.02:
                best_b, best_rate = b, rate
            elif rate < best_rate * 0.85:
                break
        self.batch = best_b
        self.fit["calibration_items_per_s"] = rates
        log.info("calibrated batch %d for %s: %s", best_b, self.key, rates)
        self._save("calibrated")
        return self.batch

    def on_oom(self) -> int:
        self.batch = max(1, (self.batch or 2) // 2)
        log.warning("OOM: batch for %s halved to %d", self.key, self.batch)
        self._save("oom")
        return self.batch

    def set(self, batch: int, reason: str) -> None:
        self.batch = max(1, min(self.max_batch, batch))
        self._save(reason)


def measure_peak(fn: Callable[[], object]) -> int:
    import torch

    torch.cuda.synchronize()
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    fn()
    torch.cuda.synchronize()
    return torch.cuda.max_memory_allocated()

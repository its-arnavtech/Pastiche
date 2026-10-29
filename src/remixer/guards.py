"""Run guards, checked by every long-running worker between units of work.

Stable (default, decision 0030): disk floor 10 GB, plus a "reduce" signal when the 10 s median of the
CPU zone reaches 93 C (the sensor tops out at 95.9 C, so the old 97 C cutoff could never fire).
Unleashed (explicit `--unleashed`): thermals, battery and throttle reasons are logged, never acted on. The one
floor that stays: free disk below 10 GB pauses writers and purges caches inside the data dir.
Safe (`--safe` / REMIXER_SAFE=1 / profile mode: safe): disk 25 GB, pause on battery, reduce at
GPU 90 C / CPU 100 C, hard pause at GPU 95 C / CPU 105 C.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger("remixer.guards")


@dataclass(frozen=True)
class Limits:
    disk_floor_gb: float
    pause_on_battery: bool
    gpu_reduce_c: float | None
    gpu_pause_c: float | None
    cpu_reduce_c: float | None
    cpu_pause_c: float | None


UNLEASHED = Limits(10.0, False, None, None, None, None)
STABLE = Limits(10.0, False, None, None, 93.0, None)
SAFE = Limits(25.0, True, 90.0, 95.0, 100.0, 105.0)


@dataclass
class Readings:
    free_disk_gb: float
    on_battery: bool | None = None
    gpu_temp_c: float | None = None
    cpu_temp_c: float | None = None
    gpu_throttle: list[str] = field(default_factory=list)


@dataclass
class Decision:
    action: str  # ok | reduce | pause | pause_writes
    reasons: list[str]
    readings: Readings

    @property
    def scale(self) -> float:
        """Suggested load factor: 1.0 normally, 0.5 when reducing."""
        return 0.5 if self.action == "reduce" else 1.0


_THROTTLE_BITS = {
    0x2: "applications_clocks", 0x4: "sw_power_cap", 0x8: "hw_slowdown", 0x10: "sync_boost",
    0x20: "sw_thermal", 0x40: "hw_thermal", 0x80: "hw_power_brake", 0x100: "display_clocks",
}


def read_sensors(data_dir: Path) -> Readings:
    """Best-effort sensor read. Missing sensors are None, never an error."""
    r = Readings(free_disk_gb=shutil.disk_usage(data_dir).free / 1e9)
    try:
        import psutil

        b = psutil.sensors_battery()
        r.on_battery = None if b is None else not b.power_plugged
    except Exception:
        pass
    try:
        import pynvml

        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        r.gpu_temp_c = float(pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU))
        mask = pynvml.nvmlDeviceGetCurrentClocksEventReasons(h)
        r.gpu_throttle = [name for bit, name in _THROTTLE_BITS.items() if mask & bit]
    except Exception:
        pass
    try:
        from remixer.telemetry.cpu_temp import read_cpu_temp, read_zone_temp

        r.cpu_temp_c = read_cpu_temp()
        if r.cpu_temp_c is None:
            r.cpu_temp_c = read_zone_temp()
    except Exception:
        pass
    return r


def purge_caches(data_dir: Path) -> int:
    """Delete only <data>/cache contents. Never touches anything else."""
    cache = (Path(data_dir) / "cache").resolve()
    if not cache.is_dir() or Path(data_dir).resolve() not in cache.parents:
        return 0
    freed = 0
    for p in cache.iterdir():
        try:
            if p.is_dir():
                freed += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                shutil.rmtree(p)
            else:
                freed += p.stat().st_size
                p.unlink()
        except OSError:
            continue
    return freed


class Guard:
    def __init__(self, data_dir: Path, mode: str = "stable",
                 sensors: Callable[[Path], Readings] = read_sensors, log_every_s: float = 30.0):
        self.data_dir = Path(data_dir)
        self.mode = mode
        self.limits = {"safe": SAFE, "unleashed": UNLEASHED}.get(mode, STABLE)
        # The ACPI zone spikes 15-20 C on single boosts: stable mode acts on a rolling median.
        self._cpu_hist: deque[float] = deque(maxlen=5)
        self.sensors = sensors
        self.log_every_s = log_every_s
        self._last_log = 0.0
        self._last_warn = 0.0
        self.interventions: list[dict] = []

    def check(self) -> Decision:
        r = self.sensors(self.data_dir)
        if self.mode == "stable" and r.cpu_temp_c is not None:
            self._cpu_hist.append(r.cpu_temp_c)
            if len(self._cpu_hist) >= 3:
                r.cpu_temp_c = statistics.median(self._cpu_hist)
            else:
                r.cpu_temp_c = None  # too few samples to trust a spike
        L = self.limits
        reasons, action = [], "ok"
        if r.free_disk_gb < L.disk_floor_gb:
            freed = purge_caches(self.data_dir)
            r.free_disk_gb += freed / 1e9
            if r.free_disk_gb < L.disk_floor_gb:
                action = "pause_writes"
                reasons.append(f"free disk {r.free_disk_gb:.1f} GB < {L.disk_floor_gb} GB (purged {freed / 1e9:.2f} GB)")
        if L.pause_on_battery and r.on_battery:
            action, reasons = "pause", reasons + ["on battery"]
        for name, temp, red, pause in (("gpu", r.gpu_temp_c, L.gpu_reduce_c, L.gpu_pause_c),
                                       ("cpu", r.cpu_temp_c, L.cpu_reduce_c, L.cpu_pause_c)):
            if temp is None:
                continue
            if pause is not None and temp >= pause:
                action, reasons = "pause", reasons + [f"{name} {temp:.0f} C >= {pause} C"]
            elif red is not None and temp >= red and action == "ok":
                action, reasons = "reduce", reasons + [f"{name} {temp:.0f} C >= {red} C"]
        d = Decision(action, reasons, r)
        if action != "ok":
            entry = {"t": time.time(), "mode": self.mode, "action": action, "reasons": reasons, "pid": os.getpid()}
            self.interventions.append(entry)
            if time.time() - self._last_warn >= self.log_every_s:   # a hot machine would log on every unit of work
                self._last_warn = time.time()
                log.warning("guard %s: %s", action, "; ".join(reasons))
            try:  # the peak report counts these
                state = self.data_dir / "state"
                state.mkdir(parents=True, exist_ok=True)
                with open(state / "guard_interventions.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
            except OSError:
                pass
        elif time.time() - self._last_log >= self.log_every_s:
            self._last_log = time.time()
            log.info("guard ok (%s): gpu %s C cpu %s C battery=%s throttle=%s disk %.0f GB",
                     self.mode, r.gpu_temp_c, r.cpu_temp_c, r.on_battery, r.gpu_throttle, r.free_disk_gb)
        return d

    def gate(self, writer: bool = True, poll_s: float = 10.0) -> Decision:
        """Block while the guard says pause (or pause_writes for writers). Returns the last decision."""
        while True:
            d = self.check()
            if d.action == "pause" or (writer and d.action == "pause_writes"):
                time.sleep(poll_s)
                continue
            return d


_guard: Guard | None = None


def get_guard(data_dir: Path | None = None, mode: str | None = None) -> Guard:
    global _guard
    if _guard is None or (mode and _guard.mode != mode):
        from remixer.config import data_dir as default_dir, load_profile

        _guard = Guard(data_dir or default_dir(), mode or load_profile().mode)
    return _guard

"""Portable process-pool budgets, disk guards, atomic checkpoints and sampling."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import threading
import time

import psutil
import yaml


def configured_workers(requested: int | None = None, *, npu_active: bool = False) -> int:
    from remixer.config import REPO_ROOT
    path = Path(os.environ.get("REMIXER_RESOURCES", str(REPO_ROOT / "config/resources.yaml")))
    config = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    actual = os.cpu_count() or 1
    reserve = max(1, int(config.get("reserve", {}).get("logical_cores", 1)))
    feeders = min(int(config.get("gpu_lane", {}).get("feeder_cores", 4)), max(0, actual - reserve - 1))
    available = max(1, actual - reserve - feeders)
    budget = min(int(config.get("cpu_lane", {}).get("workers", available)), available)
    from remixer.presets import worker_cap

    if (cap := worker_cap()) is not None:  # stable preset (decision 0030); --unleashed lifts it
        budget = min(budget, cap)
    lock = REPO_ROOT / ".locks/npu.json"
    if lock.exists():
        from datetime import datetime, timezone
        try:
            held = json.loads(lock.read_text())
            npu_active |= datetime.fromisoformat(held["expires_at"].replace("Z", "+00:00")) > datetime.now(timezone.utc)
        except (ValueError, KeyError):
            pass
    if npu_active:
        budget = max(1, budget - int(config.get("npu_lane", {}).get("host_threads", 1)))
    if requested is not None and requested < 1:
        raise ValueError("workers must be positive")
    return min(requested or budget, budget)


def _initialize_worker(affinity: list[int] | None) -> None:
    if affinity:
        psutil.Process().cpu_affinity(affinity)


def process_pool(workers: int, affinity: list[int] | None = None) -> ProcessPoolExecutor:
    # Children inherit these before importing NumPy / BLAS under spawn.
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    return ProcessPoolExecutor(max_workers=configured_workers(workers), mp_context=mp.get_context("spawn"),
                               initializer=_initialize_worker, initargs=(affinity,))


def guarded(destination: Path) -> None:
    """Writers pause at the shared guard's disk floor; never purge source audio."""
    destination.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination).free < 10 * 1024**3:
        raise OSError("disk floor: less than 10 GiB free; writer paused")
    from remixer.guards import get_guard
    decision = get_guard().check()
    if decision.action in {"pause", "pause_writes"}:
        raise OSError("shared guard paused writer: " + "; ".join(decision.reasons))


class LaneMonitor:
    """Sample host utilization separately from process-tree memory and CPU time."""

    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self.rows: list[dict] = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.process = psutil.Process()

    def __enter__(self):
        self.started = time.perf_counter()
        self.io_start = psutil.disk_io_counters()
        self.thread.start()
        return self

    def _run(self):
        psutil.cpu_percent(percpu=True)
        while not self.stop.wait(self.interval):
            processes = [self.process, *self.process.children(recursive=True)]
            rss, cpu = 0, 0.0
            for process in processes:
                try:
                    rss += process.memory_info().rss
                    times = process.cpu_times()
                    cpu += times.user + times.system
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            from remixer.guards import get_guard, read_sensors
            readings = read_sensors(get_guard().data_dir)
            self.rows.append({"elapsed": time.perf_counter() - self.started, "wall_time": time.time(),
                              "per_core_cpu_percent": psutil.cpu_percent(percpu=True),
                              "process_tree_rss_bytes": rss, "process_tree_cpu_seconds": cpu,
                              "system_memory_used_bytes": psutil.virtual_memory().used,
                              "cpu_temperature_c": readings.cpu_temp_c, "gpu_temperature_c": readings.gpu_temp_c,
                              "on_battery": readings.on_battery, "gpu_throttle": readings.gpu_throttle})

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()
        self.elapsed = time.perf_counter() - self.started
        self.io_end = psutil.disk_io_counters()

    def summary(self) -> dict:
        cpu = [sum(row["per_core_cpu_percent"]) / len(row["per_core_cpu_percent"]) for row in self.rows]
        return {"samples": len(self.rows), "system_cpu_mean_percent": sum(cpu) / len(cpu) if cpu else None,
                "system_cpu_peak_percent": max(cpu, default=None),
                "per_core_peak_percent": [max(row["per_core_cpu_percent"][i] for row in self.rows)
                                          for i in range(len(self.rows[0]["per_core_cpu_percent"]))] if self.rows else [],
                "process_tree_peak_rss_bytes": max((row["process_tree_rss_bytes"] for row in self.rows), default=None),
                "system_memory_peak_bytes": max((row["system_memory_used_bytes"] for row in self.rows), default=None),
                "system_disk_read_bytes_per_second": (self.io_end.read_bytes - self.io_start.read_bytes) / self.elapsed,
                "system_disk_write_bytes_per_second": (self.io_end.write_bytes - self.io_start.write_bytes) / self.elapsed,
                "cpu_temperature_c": max((row["cpu_temperature_c"] for row in self.rows if row["cpu_temperature_c"] is not None), default=None),
                "gpu_temperature_peak_c": max((row["gpu_temperature_c"] for row in self.rows if row["gpu_temperature_c"] is not None), default=None),
                "battery_observed": any(row["on_battery"] is True for row in self.rows),
                "gpu_throttle_reasons": sorted({reason for row in self.rows for reason in row["gpu_throttle"]}),
                "sample_series": self.rows,
                "cpu_temperature_note": "Optional shared sensor adapter; null means unavailable"}

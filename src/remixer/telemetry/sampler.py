"""Telemetry sampler: every 1-2 s, one row of machine state, flushed to Parquet part files.

Columns: ts; gpu_util, gpu_mem_util, vram_used_gib, vram_total_gib, gpu_temp_c, gpu_power_w,
gpu_power_limit_w, gpu_sm_mhz, gpu_mem_mhz, gpu_pstate, gpu_throttle (bitmask) and
gpu_throttle_names; cpu_util, cpu_00..cpu_NN, cpu_mhz; ram_used_gib, ram_util, swap_used_gib;
disk_read_mbs, disk_write_mbs; cpu_temp_c (optional); igpu/npu engine utilization (Windows,
best effort); plus `tag` (the current bench phase).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import psutil

log = logging.getLogger("remixer.telemetry")


class Sampler:
    def __init__(self, out_dir: Path, interval_s: float = 1.0, flush_every: int = 30):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.interval = interval_s
        self.flush_every = flush_every
        self.rows: list[dict] = []
        self.tag = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._parts = 0
        self._nv = self._init_nvml()
        from remixer.telemetry.win_engines import EngineSampler

        self._eng = EngineSampler()
        self._last_disk = psutil.disk_io_counters()
        self._last_t = time.perf_counter()
        psutil.cpu_percent(percpu=True)

    @staticmethod
    def _init_nvml():
        try:
            import pynvml

            pynvml.nvmlInit()
            return pynvml.nvmlDeviceGetHandleByIndex(0)
        except Exception:
            return None

    def sample(self) -> dict:
        now = time.perf_counter()
        row: dict = {"ts": time.time(), "tag": self.tag}
        per = psutil.cpu_percent(percpu=True)
        row["cpu_util"] = sum(per) / len(per)
        for i, v in enumerate(per):
            row[f"cpu_{i:02d}"] = v
        try:
            row["cpu_mhz"] = psutil.cpu_freq().current
        except Exception:
            row["cpu_mhz"] = None
        vm, sw = psutil.virtual_memory(), psutil.swap_memory()
        row.update(ram_used_gib=(vm.total - vm.available) / 2**30, ram_util=vm.percent, swap_used_gib=sw.used / 2**30)
        d = psutil.disk_io_counters()
        dt = max(now - self._last_t, 1e-6)
        if d and self._last_disk:
            row["disk_read_mbs"] = (d.read_bytes - self._last_disk.read_bytes) / dt / 1e6
            row["disk_write_mbs"] = (d.write_bytes - self._last_disk.write_bytes) / dt / 1e6
        self._last_disk, self._last_t = d, now
        if self._nv is not None:
            row.update(self._gpu())
        try:
            from remixer.telemetry.cpu_temp import read_cpu_temp

            row["cpu_temp_c"] = read_cpu_temp()
        except Exception:
            row["cpu_temp_c"] = None
        for k, v in self._eng.sample().items():
            if k in ("igpu", "npu", "igpu_compute", "igpu_3d", "npu_compute"):
                row[k] = v
        return row

    def _gpu(self) -> dict:
        import pynvml

        from remixer.guards import _THROTTLE_BITS

        h = self._nv
        out = {}

        def read(names, fn):
            # NVML calls fail transiently on Optimus laptops; one failed field must not blank the row.
            for attempt in range(2):
                try:
                    vals = fn()
                    out.update(zip(names, vals if isinstance(vals, tuple) else (vals,)))
                    return
                except Exception as e:
                    if attempt:
                        log.debug("nvml %s failed: %s", names, e)

        def util():
            u = pynvml.nvmlDeviceGetUtilizationRates(h)
            return u.gpu, u.memory

        def mem():
            m = pynvml.nvmlDeviceGetMemoryInfo(h)
            return m.used / 2**30, m.total / 2**30

        read(("gpu_util", "gpu_mem_util"), util)
        read(("vram_used_gib", "vram_total_gib"), mem)
        read(("gpu_temp_c",), lambda: pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU))
        read(("gpu_power_w",), lambda: pynvml.nvmlDeviceGetPowerUsage(h) / 1000)
        read(("gpu_power_limit_w",), lambda: pynvml.nvmlDeviceGetEnforcedPowerLimit(h) / 1000)
        read(("gpu_sm_mhz",), lambda: pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_SM))
        read(("gpu_mem_mhz",), lambda: pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_MEM))
        read(("gpu_pstate",), lambda: pynvml.nvmlDeviceGetPerformanceState(h))
        read(("gpu_throttle",), lambda: int(pynvml.nvmlDeviceGetCurrentClocksEventReasons(h)))
        if "gpu_throttle" in out:
            out["gpu_throttle_names"] = ",".join(n for b, n in _THROTTLE_BITS.items() if out["gpu_throttle"] & b)
        return out

    def _run(self) -> None:
        nxt = time.perf_counter()
        while not self._stop.is_set():
            try:
                self.rows.append(self.sample())
            except Exception as e:
                log.warning("sample failed: %s", e)
            if len(self.rows) >= self.flush_every:
                self.flush()
            nxt += self.interval
            self._stop.wait(max(0.0, nxt - time.perf_counter()))
        self.flush()

    def flush(self) -> None:
        rows, self.rows = self.rows, []
        if not rows:
            return
        import pyarrow as pa
        import pyarrow.parquet as pq

        self._parts += 1
        path = self.out_dir / f"part-{os.getpid()}-{self._parts:05d}.parquet"
        tmp = path.with_suffix(".parquet.tmp")
        pq.write_table(pa.Table.from_pylist(rows), tmp)
        os.replace(tmp, path)

    def start(self) -> "Sampler":
        self._thread = threading.Thread(target=self._run, name="telemetry", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)


def load(out_dir: Path):
    """All telemetry rows under out_dir as a pyarrow Table (schema-merged), sorted by ts."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    parts = [pq.read_table(p) for p in sorted(Path(out_dir).rglob("*.parquet"))]
    if not parts:
        return pa.table({"ts": pa.array([], pa.float64())})
    t = pa.concat_tables(parts, promote_options="permissive")
    return t.take(pc.sort_indices(t, sort_keys=[("ts", "ascending")]))

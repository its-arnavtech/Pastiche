"""Local ComputeBackend: CUDA via torch + pynvml, CPU via psutil. NPU/iGPU listed via OpenVINO if installed."""
from __future__ import annotations

from remixer.config import Resources
from remixer.interfaces import ComputeBackend, DeviceInfo


def nvml_handle(index: int = 0):
    try:
        import pynvml

        pynvml.nvmlInit()
        return pynvml.nvmlDeviceGetHandleByIndex(index)
    except Exception:
        return None


AFFINITY_ENV = "REMIXER_CPU_AFFINITY"


def core_plan(resources: Resources, topology: dict | None = None) -> dict[str, list[int]]:
    """Disjoint logical-CPU sets per lane (decision 0024), or {} when the topology is unknown.

    gpu: one P-core (both threads) for kernel launches plus `gpu_feeders` E-cores for decode/prefetch;
    npu: `npu_host_threads` of the slowest cores; reserve: the next slowest; cpu: everything else.
    """
    if topology is None:
        from remixer.adapters.cpu_topology import cpu_sets

        topology = cpu_sets()
    rows = topology.get("rows") or []
    if topology.get("reason") or not rows:
        return {}
    classes = sorted({r["efficiency_class"] for r in rows})
    by_class = {c: [r for r in rows if r["efficiency_class"] == c] for c in classes}
    perf = by_class[classes[-1]]
    first_core = perf[0]["core_index"]
    gpu = [r["logical_processor"] for r in perf if r["core_index"] == first_core]
    # The last efficiency-class CPUs (Meteor Lake's low-power island) host the NPU thread and the reserve.
    eff = [r["logical_processor"] for c in classes[:-1] for r in by_class[c]]
    lp = eff[-(resources.npu_host_threads + resources.reserve):]
    npu, reserve = lp[:resources.npu_host_threads], lp[resources.npu_host_threads:]
    gpu += [c for c in eff if c not in lp][:resources.gpu_feeders]
    taken = set(gpu) | set(npu) | set(reserve)
    cpu = [r["logical_processor"] for r in rows if r["logical_processor"] not in taken]
    return {"gpu": sorted(gpu), "cpu": sorted(cpu), "npu": sorted(npu), "reserve": sorted(reserve)}


def pin_from_env() -> list[int] | None:
    """Apply REMIXER_CPU_AFFINITY (comma-separated logical CPUs) to this process; children inherit it."""
    import os

    import psutil

    raw = os.environ.get(AFFINITY_ENV)
    if not raw:
        return None
    cores = [int(x) for x in raw.split(",") if x.strip()]
    try:
        psutil.Process().cpu_affinity(cores)
    except (psutil.Error, OSError, ValueError):
        return None
    return cores


class LocalCompute(ComputeBackend):
    def __init__(self, resources: Resources):
        self.resources = resources
        self._h = nvml_handle()

    def devices(self) -> list[DeviceInfo]:
        import psutil

        out = [DeviceInfo(name="cpu", kind="cpu", total_memory=psutil.virtual_memory().total,
                          free_memory=psutil.virtual_memory().available,
                          extra={"logical": self.resources.logical_cores, "physical": self.resources.physical_cores})]
        if self._h is not None:
            import pynvml

            mem = pynvml.nvmlDeviceGetMemoryInfo(self._h)
            name = pynvml.nvmlDeviceGetName(self._h)
            out.append(DeviceInfo(name=name if isinstance(name, str) else name.decode(), kind="cuda",
                                  total_memory=mem.total, free_memory=mem.free))
        try:
            import openvino as ov

            for d in ov.Core().available_devices:
                if d.startswith(("NPU", "GPU")):
                    out.append(DeviceInfo(name=d, kind="npu" if d.startswith("NPU") else "igpu"))
        except Exception:
            pass
        return out

    def torch_device(self) -> str:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"

    def free_vram(self) -> int:
        """Free VRAM in bytes as the driver sees it (other processes included)."""
        if self._h is None:
            return 0
        import pynvml

        return pynvml.nvmlDeviceGetMemoryInfo(self._h).free

    def prioritize_current_process(self, lane: str) -> str:
        """GPU-lane processes run above normal so CPU-lane saturation cannot starve the GPU feeders.

        Only this process's own scheduling priority changes; nothing system-wide.
        """
        import psutil

        p = psutil.Process()
        try:
            if lane == "gpu":
                p.nice(psutil.ABOVE_NORMAL_PRIORITY_CLASS if hasattr(psutil, "ABOVE_NORMAL_PRIORITY_CLASS") else -5)
            return str(p.nice())
        except (psutil.AccessDenied, OSError) as e:
            return f"unchanged ({e})"

    def core_plan(self) -> dict[str, list[int]]:
        return core_plan(self.resources)

    def cpu_workers(self, lane: str = "cpu") -> int:
        r = self.resources
        return {"cpu": r.cpu_workers, "gpu": r.gpu_feeders, "npu": r.npu_host_threads}[lane]

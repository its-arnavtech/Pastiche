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

    def cpu_workers(self, lane: str = "cpu") -> int:
        r = self.resources
        return {"cpu": r.cpu_workers, "gpu": r.gpu_feeders, "npu": r.npu_host_threads}[lane]

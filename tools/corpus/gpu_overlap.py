"""Read-only NVIDIA overlap evidence for the CPU peak; never owns GPU compute."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time


def main():
    import pynvml
    from remixer.adapters.local_compute import nvml_handle
    from remixer.corpus.generate import atomic_json
    from remixer.cpu.runtime import guarded
    from remixer.telemetry.win_engines import EngineSampler
    data = Path(os.environ.get("REMIXER_DATA_DIR", "data"))
    output = data / "cpu-peak/gpu-overlap.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    handle = nvml_handle()
    engines = EngineSampler()
    rows = []
    with output.open("a", encoding="utf-8") as stream:
        while True:
            state_path = data / "cpu-peak/runner.json"
            phase = json.loads(state_path.read_text()).get("phase") if state_path.exists() else "waiting"
            if phase == "complete":
                break
            row = {"wall_time": time.time(), "cpu_phase": phase}
            if handle is not None:
                try:
                    utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    row.update({"gpu_utilization_percent": utilization.gpu,
                                "memory_used_bytes": pynvml.nvmlDeviceGetMemoryInfo(handle).used,
                                "temperature_c": pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)})
                except pynvml.NVMLError as exc:
                    row["unavailable"] = type(exc).__name__
            else:
                row["unavailable"] = "NVML handle unavailable"
            engine_values = engines.sample()
            row["igpu_utilization_percent"] = engine_values.get("igpu")
            if "gpu_utilization_percent" not in row:
                nvidia = [value for name, value in engine_values.items() if name.startswith("nvidia_")]
                if nvidia:
                    row["gpu_utilization_percent"] = max(nvidia)
                    row["gpu_utilization_source"] = "windows_pdh_busiest_engine"
            else:
                row["gpu_utilization_source"] = "nvml"
            guarded(output.parent)
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            rows.append(row)
            time.sleep(1)
    values = [row["gpu_utilization_percent"] for row in rows if "gpu_utilization_percent" in row]
    atomic_json(output.with_suffix(".json"), {"samples": len(rows), "available_samples": len(values),
                "gpu_mean_percent": sum(values) / len(values) if values else None,
                "gpu_above_90_fraction": sum(value > 90 for value in values) / len(values) if values else None})


if __name__ == "__main__":
    main()

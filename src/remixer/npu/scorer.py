"""Static MLP IR export, validated device execution, sustained inference loops."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import os
from pathlib import Path
import time

import numpy as np

from remixer.corpus.generate import atomic_json
from remixer.cpu.runtime import LaneMonitor, guarded

os.environ.setdefault("OPENVINO_TELEMETRY", "0")


@dataclass(frozen=True)
class ScorerSpec:
    features: int = 512
    hidden: int = 256
    batch: int = 128
    seed: int = 0


def weights(spec: ScorerSpec):
    rng = np.random.default_rng(spec.seed)
    return (rng.normal(0, .04, (spec.features, spec.hidden)).astype(np.float32),
            rng.normal(0, .02, (spec.hidden, 64)).astype(np.float32),
            rng.normal(0, .04, (64, 1)).astype(np.float32))


def reference_score(inputs: np.ndarray, spec: ScorerSpec) -> np.ndarray:
    a, b, c = weights(spec)
    return 1 / (1 + np.exp(-(np.maximum(0, np.maximum(0, inputs @ a) @ b) @ c)))


def export_scorer(destination: Path, spec: ScorerSpec = ScorerSpec()) -> Path:
    import openvino as ov
    from openvino import opset13 as op
    if min(spec.features, spec.hidden, spec.batch) < 1:
        raise ValueError("scorer dimensions must be positive")
    destination.mkdir(parents=True, exist_ok=True)
    a, b, c = weights(spec)
    inputs = op.parameter([spec.batch, spec.features], np.float32, name="embeddings")
    hidden = op.relu(op.matmul(inputs, op.constant(a), False, False))
    hidden = op.relu(op.matmul(hidden, op.constant(b), False, False))
    result = op.sigmoid(op.matmul(hidden, op.constant(c), False, False))
    model = ov.Model([result], [inputs], "synthetic-scorer-v1")
    path = destination / "scorer.xml"
    ov.save_model(model, path, compress_to_fp16=False)
    atomic_json(destination / "model.json", {**spec.__dict__, "version": "synthetic-scorer-v1", "synthetic": True,
                                              "trained_taste_model": False, "openvino_version": ov.__version__})
    return path


class OpenVINOScorer:
    def __init__(self, model: Path, spec: ScorerSpec, device: str = "NPU", core=None):
        import openvino as ov
        self.spec = spec
        self.core = core or ov.Core()
        self.requested_device, self.fallback_reason = device, None
        config = {"INFERENCE_NUM_THREADS": 1} if device == "CPU" else {}
        try:
            if device.startswith("GPU"):
                if device == "GPU":
                    choices = [name for name in self.core.available_devices if name.startswith("GPU")
                               and "intel" in str(self.core.get_property(name, "FULL_DEVICE_NAME")).lower()]
                    if not choices:
                        raise RuntimeError("no Intel GPU; NVIDIA lane is excluded")
                    device = choices[0]
                if "intel" not in str(self.core.get_property(device, "FULL_DEVICE_NAME")).lower():
                    raise RuntimeError("requested GPU is not Intel; NVIDIA lane is excluded")
            self.compiled = self.core.compile_model(str(model), device, config)
            self.device = device
        except Exception as exc:
            if device == "CPU":
                raise
            self.fallback_reason = f"{type(exc).__name__}: {exc}"
            self.compiled = self.core.compile_model(str(model), "CPU", {"INFERENCE_NUM_THREADS": 1})
            self.device = "CPU"
        self.request = self.compiled.create_infer_request()

    def score(self, embeddings: np.ndarray) -> np.ndarray:
        if embeddings.shape != (self.spec.batch, self.spec.features):
            raise ValueError("input must match static scorer shape")
        result = self.request.infer({0: np.ascontiguousarray(embeddings, dtype=np.float32)})
        return np.array(result[self.compiled.output(0)], copy=True)


def benchmark_device(model: Path, spec: ScorerSpec, device: str, seconds: float, destination: Path) -> dict:
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    guarded(destination)
    compile_started = time.perf_counter()
    scorer = OpenVINOScorer(model, spec, device)
    compile_seconds = time.perf_counter() - compile_started
    inputs = np.random.default_rng(17).normal(size=(spec.batch, spec.features)).astype(np.float32)
    expected = reference_score(inputs, spec)
    actual = scorer.score(inputs)
    max_error = float(np.max(np.abs(expected - actual)))
    if max_error > .01 or not np.isfinite(actual).all():
        raise ValueError(f"device scorer validation error: {max_error}")
    # Warm-up excludes compilation, memory allocation and first-use kernels.
    for _ in range(5):
        scorer.score(inputs)
    started, batches = time.perf_counter(), 0
    with LaneMonitor() as monitor:
        while time.perf_counter() - started < seconds:
            scorer.score(inputs)
            batches += 1
            if batches % 100 == 0:
                guarded(destination)
                atomic_json(destination / f"{device.replace('.', '-')}-checkpoint.json",
                            {"batches": batches, "elapsed": time.perf_counter() - started, "device": scorer.device})
    elapsed = time.perf_counter() - started
    row = {"requested_device": device, "executed_device": scorer.device,
           "full_device_name": str(scorer.core.get_property(scorer.device, "FULL_DEVICE_NAME")),
           "fallback_reason": scorer.fallback_reason, "compile_seconds": compile_seconds,
           "wall_seconds": elapsed, "batches": batches, "batch_size": spec.batch,
           "inferences_per_second": batches * spec.batch / elapsed, "max_reference_error": max_error,
           "synthetic": True, **monitor.summary()}
    atomic_json(destination / f"{device.replace('.', '-')}-benchmark.json", row)
    return row


def benchmark(destination: Path, seconds: float = 600, devices: tuple[str, ...] = ("NPU", "GPU.0", "CPU"),
              *, parallel: bool = False, spec: ScorerSpec = ScorerSpec()) -> dict:
    import openvino as ov
    destination.mkdir(parents=True, exist_ok=True)
    model = export_scorer(destination, spec)
    core = ov.Core()
    available = {device: str(core.get_property(device, "FULL_DEVICE_NAME")) for device in core.available_devices}
    # Enumerate and validate vendor explicitly: recent OpenVINO can list NVIDIA.
    if parallel:
        with ThreadPoolExecutor(max_workers=len(devices)) as pool:
            results = list(pool.map(lambda device: benchmark_device(model, spec, device, seconds, destination), devices))
    else:
        results = [benchmark_device(model, spec, device, seconds, destination) for device in devices]
    result = {"stage": "npu", "available_devices": available, "parallel": parallel,
              "openvino_version": ov.__version__, "results": results}
    atomic_json(destination / "benchmark.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(os.environ.get("REMIXER_DATA_DIR", "data")) / "npu")
    parser.add_argument("--seconds", type=float, default=600)
    parser.add_argument("--devices", nargs="+", default=["NPU", "GPU.0", "CPU"])
    parser.add_argument("--parallel", action="store_true")
    args = parser.parse_args()
    print(json.dumps(benchmark(args.output, args.seconds, tuple(args.devices), parallel=args.parallel), indent=2))


if __name__ == "__main__":
    main()

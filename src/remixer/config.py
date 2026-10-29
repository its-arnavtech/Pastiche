"""Profile and resource configuration.

`profile.yaml` (repo root, or REMIXER_PROFILE) selects adapters and limits;
`config/resources.yaml` holds lane budgets. Neither is read by core logic directly:
core code receives already-built adapters.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from remixer.presets import STABLE_DEFAULTS

REPO_ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    d = Path(os.environ.get("REMIXER_DATA_DIR") or REPO_ROOT / "data")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


DEFAULT_PROFILE: dict[str, Any] = {
    "name": "local-max",
    "mode": "stable",  # stable (default, capped) | unleashed (explicit --unleashed) | safe
    "adapters": {
        "blob_store": "fs",
        "catalog": "sqlite",
        "event_sink": "parquet",
        "vector_index": "hnsw",
        "job_queue": "sqlite",
        "compute": "local",
        "llm": "ollama",
    },
    "paths": {
        "catalog": "catalog.sqlite",
        "jobs": "jobs.sqlite",
        "blobs": "blobs",
        "events": "events",
        "vectors": "vectors",
        "cache": "cache",
        "telemetry": "telemetry",
    },
    "gpu": {
        "separation_model": "htdemucs",
        "heavy_model": "htdemucs_ft",
        "heavy_shifts": 2,
        "fp16": True,
        "embedding_model": "laion/clap-htsat-unfused",
        "window_s": 5.0,
    },
    "stable": dict(STABLE_DEFAULTS),
    "llm": {"url": "http://127.0.0.1:11434", "model": "llama3.2:3b"},
    "telemetry": {"interval_s": 1.0},
}


@dataclass
class Resources:
    logical_cores: int
    physical_cores: int
    reserve: int = 1
    gpu_feeders: int = 4
    prefetch_batches: int = 2
    npu_host_threads: int = 1
    cpu_cap: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def cpu_workers(self) -> int:
        n = max(1, self.logical_cores - self.gpu_feeders - self.reserve)
        return min(n, self.cpu_cap) if self.cpu_cap else n


def compute_resources(raw: dict[str, Any] | None = None, logical: int | None = None) -> Resources:
    """Budgets from the real core count. Reserve is clamped to >= 1 (never zero)."""
    raw = raw or {}
    import psutil

    logical = logical or os.cpu_count() or 1
    physical = psutil.cpu_count(logical=False) or logical
    reserve = max(1, int(raw.get("reserve", {}).get("logical_cores", 1)))
    gpu = raw.get("gpu_lane", {})
    feeders = min(int(gpu.get("feeder_cores", 4)), max(1, logical - reserve - 1))
    return Resources(
        logical_cores=logical,
        physical_cores=physical,
        reserve=reserve,
        gpu_feeders=feeders,
        prefetch_batches=int(gpu.get("prefetch_batches", 2)),
        npu_host_threads=int(raw.get("npu_lane", {}).get("host_threads", 1)),
        raw=raw,
    )


@dataclass
class Profile:
    raw: dict[str, Any]
    resources: Resources
    data_dir: Path

    @property
    def mode(self) -> str:
        return self.raw.get("mode", "stable")

    def path(self, name: str) -> Path:
        return self.data_dir / self.raw["paths"][name]

    def __getitem__(self, k: str) -> Any:
        return self.raw[k]


def load_profile(path: str | Path | None = None, overrides: dict | None = None) -> Profile:
    path = Path(path or os.environ.get("REMIXER_PROFILE") or REPO_ROOT / "profile.yaml")
    raw = _deep_merge(DEFAULT_PROFILE, _load_yaml(path))
    if overrides:
        raw = _deep_merge(raw, overrides)
    if os.environ.get("REMIXER_UNLEASHED") == "1":
        raw["mode"] = "unleashed"
    elif os.environ.get("REMIXER_SAFE") == "1":
        raw["mode"] = "safe"
    res_path = REPO_ROOT / "config" / "resources.yaml"
    resources = compute_resources(_load_yaml(res_path))
    if raw["mode"] != "unleashed":  # the stable preset caps the CPU lane (decision 0030)
        resources.cpu_cap = int(raw["stable"]["cpu_workers"])
    return Profile(raw=raw, resources=resources, data_dir=data_dir())


def resources_yaml(res: Resources, ram_gb: float, vram_gb: float) -> str:
    return yaml.safe_dump({
        "machine": {"logical_cores": res.logical_cores, "physical_cores": res.physical_cores,
                    "ram_gb": round(ram_gb, 1), "vram_gb": round(vram_gb, 1)},
        "reserve": {"logical_cores": res.reserve},
        "gpu_lane": {"feeder_cores": res.gpu_feeders, "exclusive": True, "prefetch_batches": res.prefetch_batches},
        "cpu_lane": {"workers": res.cpu_workers},
        "npu_lane": {"host_threads": res.npu_host_threads, "devices": ["NPU", "GPU.0"]},
    }, sort_keys=False)

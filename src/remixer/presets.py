"""The stable preset: the capped configuration that survived the laptop shutdowns (decisions 0025, 0026, 0030).

It is the default. The old uncapped behaviour is still there, behind an explicit `--unleashed`
(or REMIXER_UNLEASHED=1), and always prints a warning: two uncapped runs powered this laptop off.
"""
from __future__ import annotations

import os
import sys
from typing import Any

# The CPU package zone (ACPI _TZ.THRM) tops out at 95.9 C on this machine. A cutoff above that can never
# fire (the old 97 C never did), so the stable cutoff sits below it.
SENSOR_MAX_C = 95.9

STABLE_DEFAULTS: dict[str, Any] = {
    "cpu_workers": 8,             # CPU render lane
    "separation_model": "htdemucs",   # light Demucs only; htdemucs_ft + shifts draws the most power for the same rate
    "gpu_batch": 8,               # upper bound; VRAM-aware sizing may choose lower
    "npu_devices": ["NPU"],       # NPU only; the iGPU shares the CPU package budget
    "watchdog": True,
    "cpu_limit_c": 93.0,          # 10 s median of the CPU zone; < SENSOR_MAX_C
    "gpu_limit_c": 94.0,          # decision 0026: 90 sat inside the GPU's own steady state
    "resume_margin_c": 8.0,
    "cooldown_c": 82.0,           # bench: wait for the CPU zone to fall below this between steps
}

UNLEASHED_WARNING = (
    "WARNING: --unleashed removes the stable preset's caps (8 CPU workers, light Demucs, batch <= 8, NPU only, "
    "thermal watchdog). Two uncapped runs on this laptop ended in an unexpected power-off (System event 6008, "
    "docs/PEAK_REPORT.md). Use at your own risk, and only with the laptop on AC power with clear vents."
)


def enable_unleashed(announce: bool = True) -> None:
    os.environ["REMIXER_UNLEASHED"] = "1"
    if announce:
        print(UNLEASHED_WARNING, file=sys.stderr, flush=True)


def current_mode() -> str:
    """stable (default) | unleashed | safe. Environment beats the profile file."""
    if os.environ.get("REMIXER_UNLEASHED") == "1":
        return "unleashed"
    if os.environ.get("REMIXER_SAFE") == "1":
        return "safe"
    try:
        from remixer.config import REPO_ROOT, _load_yaml

        path = os.environ.get("REMIXER_PROFILE") or REPO_ROOT / "profile.yaml"
        from pathlib import Path

        return str(_load_yaml(Path(path)).get("mode", "stable"))
    except Exception:
        return "stable"


def stable_settings(raw: dict | None = None) -> dict[str, Any]:
    """STABLE_DEFAULTS overlaid with the profile's `stable:` block."""
    out = dict(STABLE_DEFAULTS)
    if raw is None:
        try:
            from remixer.config import REPO_ROOT, _load_yaml
            from pathlib import Path

            raw = _load_yaml(Path(os.environ.get("REMIXER_PROFILE") or REPO_ROOT / "profile.yaml")).get("stable", {})
        except Exception:
            raw = {}
    out.update({k: v for k, v in (raw or {}).items() if k in STABLE_DEFAULTS})
    return out


def capped() -> bool:
    return current_mode() != "unleashed"


def worker_cap() -> int | None:
    """CPU render workers allowed by the active mode (None when unleashed)."""
    return int(stable_settings()["cpu_workers"]) if capped() else None


def gpu_batch_cap() -> int | None:
    return int(stable_settings()["gpu_batch"]) if capped() else None

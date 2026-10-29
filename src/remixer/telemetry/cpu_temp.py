"""Optional CPU package temperature. Windows has no unprivileged API for it, so this reads
LibreHardwareMonitor's built-in web server (Options > Remote Web Server, default port 8085)
when it is running. Returns None otherwise; nothing depends on it being available."""
from __future__ import annotations

import json
import os
import time
import urllib.request

_URL = os.environ.get("REMIXER_LHM_URL", "http://127.0.0.1:8085/data.json")
_state = {"next_try": 0.0}


def _walk(node, out):
    text = node.get("Text", "")
    if node.get("Type") == "Temperature" or (node.get("Value", "").endswith("°C") and not node.get("Children")):
        out.append((text, node.get("Value", "")))
    for c in node.get("Children", []):
        _walk(c, out)


def read_cpu_temp() -> float | None:
    if time.time() < _state["next_try"]:
        return None
    try:
        with urllib.request.urlopen(_URL, timeout=0.3) as r:
            tree = json.loads(r.read())
    except Exception:
        _state["next_try"] = time.time() + 60  # not running: back off for a minute
        return None
    temps = []
    _walk(tree, temps)
    for name, value in temps:
        if "package" in name.lower() or "cpu" in name.lower():
            try:
                return float(value.split()[0].replace(",", "."))
            except ValueError:
                continue
    return None


_zone = {"eng": None, "failed": False}


def read_zone_temp() -> float | None:
    """CPU package temperature from the ACPI thermal zone `_TZ.THRM` (Windows, no admin rights).
    Single readings spike 15-20 C: callers smooth them (guards.Guard keeps a rolling median)."""
    if _zone["failed"]:
        return None
    try:
        if _zone["eng"] is None:
            from remixer.telemetry.win_engines import EngineSampler

            _zone["eng"] = EngineSampler()
            _zone["eng"].sample()
            time.sleep(0.2)
        return _zone["eng"].sample().get("tz_thrm_c")
    except Exception:
        _zone["failed"] = True
        return None

"""Follow the per-device baseline with simultaneous NPU/iGPU saturation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    root = Path(__file__).resolve().parents[2]
    data = Path(os.environ.get("REMIXER_DATA_DIR", str(root / "data")))
    baseline = data / "npu/retry/benchmark.json"
    while not baseline.exists():
        time.sleep(5)
    from remixer.npu.scorer import benchmark_async
    from remixer.corpus.generate import atomic_json
    recovered = json.loads(baseline.read_text())
    original_npu = json.loads((data / "npu/sustain/NPU-benchmark.json").read_text())
    atomic_json(data / "npu/sustain/benchmark.json", {"stage": "npu", "results": [original_npu, *recovered["results"]],
                "recovery_note": "Original GPU run interrupted by a Windows reader-sharing race; full GPU.0 and CPU baselines rerun after bounded-retry fix."})
    try:
        print(json.dumps(benchmark_async(data / "npu/dual", seconds=600), indent=2))
    finally:
        subprocess.run([sys.executable, str(root / "scripts/agentctl.py"), "lock", "release", "npu", "--owner", "gpt-sol"],
                       cwd=root, check=True)


if __name__ == "__main__":
    main()

"""Keep both Intel engines active through the CPU peak, with one host loop."""
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
    while not (data / "npu/dual/benchmark.json").exists():
        time.sleep(1)
    # The preceding dispatcher releases its lock in finally. Wait for that exact
    # handoff, so it cannot remove a newly renewed lease after this acquisition.
    while (root / ".locks/npu.json").exists():
        time.sleep(.25)
    def coordination(*arguments):
        subprocess.run([sys.executable, str(root / "scripts/agentctl.py"), *arguments], cwd=root, check=True)
    coordination("lock", "acquire", "npu", "--owner", "gpt-sol", "--ttl", "180", "--note", "Intel NPU+iGPU held through CPU peak sustain")
    from remixer.npu.scorer import benchmark_async
    def complete():
        return json.loads((data / "cpu-peak/runner.json").read_text()).get("phase") == "complete"
    try:
        result = benchmark_async(data / "npu/peak-hold", seconds=4000, stop_when=complete)
        print(json.dumps({key: value for key, value in result.items() if key != "sample_series"}, indent=2))
    finally:
        coordination("lock", "release", "npu", "--owner", "gpt-sol")


if __name__ == "__main__":
    main()

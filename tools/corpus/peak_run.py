"""Run the CPU tuning/sustain sequence after full corpus analysis completes.

Invoke from the repository root. Existing analysis is an independent, checkpointed
process; this runner waits on its atomic final report without taking GPU ownership.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--tune-seconds", type=float, default=15)
    parser.add_argument("--sustain-seconds", type=float, default=600)
    args = parser.parse_args()
    from remixer.cpu.tuner import sustain, tune
    from remixer.corpus.generate import atomic_json
    destination = args.data / "cpu-peak"
    destination.mkdir(parents=True, exist_ok=True)
    while not (args.data / "analysis" / "benchmark.json").exists():
        atomic_json(destination / "runner.json", {"phase": "waiting_for_analysis", "time": time.time()})
        time.sleep(5)
    analysis = json.loads((args.data / "analysis" / "benchmark.json").read_text())
    if analysis["errors"] or analysis["items"] != 2500:
        raise RuntimeError("full 500-track/2500-item analysis must succeed before peak tuning")
    atomic_json(destination / "runner.json", {"phase": "tuning", "time": time.time()})
    tuning = tune(args.data / "corpus", destination / "tuning", args.tune_seconds)
    if not all(row["converged"] for row in tuning["convergence"].values()):
        raise RuntimeError("tuning has not met the two-round convergence criterion")
    atomic_json(destination / "runner.json", {"phase": "sustain", "time": time.time()})
    result = sustain(args.data / "corpus", destination / "sustain", args.sustain_seconds,
                     destination / "tuning" / "tuning.json")
    atomic_json(destination / "runner.json", {"phase": "complete", "time": time.time(), "result": result})
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

---
ts: 2026-10-29T20:23:21Z
agent: opus-cc
branch: dev
type: bench
tasks: [T-018, T-007]
files: [docs/PEAK_REPORT.md, docs/PEAK_NOTES.md, docs/decisions/0026-peak-final-configuration.md, src/remixer/bench/report.py, tests/test_bench.py, reports/peak/, .gitignore]
---

## What changed

T-018 finished: capped round 2 (ramp + 60 min) plus tuning rounds 3-5 (15 min each), converged at -1.3 % / +1.1 %. Final config: --cool --gpu-limit-c 94 (GPU batch 8 light on CPUs 0-5, 8 render workers on 6-19, NPU-only). Peaks: GPU Demucs 66.6 audio-s/s isolated, 58.4 sustained with all lanes; CPU render 13.7 isolated, 2.9 sustained; NPU 50.7k isolated, 46.1k sustained. Report gains pass/starvation/pause columns, copies PEAK_NOTES.md, and drops invalid >2x-limit GPU power readings from old runs.

## Why

The user reported the laptop shutting itself down; every number is now the highest the machine sustains without powering off.

## How to verify

No shutdown across round 2-5 (about 2.5 h of load); tests/test_bench.py 8 passed; bench report --all regenerated.

## Next / handoff

Joint GPU>90 % + CPU-lane saturation is not reachable on this chassis (shared cooling); better cooling is the only lever (NEEDS_USER item 4).

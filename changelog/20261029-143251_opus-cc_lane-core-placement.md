---
ts: 2026-10-29T14:32:51Z
agent: opus-cc
branch: dev
type: perf
tasks: [T-018]
files: [src/remixer/adapters/local_compute.py, src/remixer/cli.py, src/remixer/gpu/prefetch.py, src/remixer/gpu/separate.py, src/remixer/bench/stress.py, src/remixer/bench/cli.py, src/remixer/bench/report.py, tests/test_core.py, docs/decisions/0024-lane-core-placement.md]
---

## What changed

Per-lane core sets (gpu 0-5 = one P-core + 4 E feeders, cpu 6-19, npu 20, reserve 21) applied by bench stress through REMIXER_CPU_AFFINITY, inherited by lane workers; GPU stays above-normal priority. GPU lane logs gpu_starvation events (NVML util < 80 % while the feeder queue was empty). Reports add per-lane core utilization, starvation counts and the pass check. Bench metadata records the Windows AC power-mode overlay (now best performance).

## Why

Round 1 showed CPU and NPU lanes collapsing under oversubscription; the GPU process alone uses ~5.4 CPUs. No opus-cc-2 affinity work exists to reconcile (decision 0024).

## How to verify

uv run pytest tests/test_core.py tests/test_bench.py tests/test_gpu_lane.py

## Next / handoff

opus-cc: T-018 ramp + 60-min sustain with pinning.

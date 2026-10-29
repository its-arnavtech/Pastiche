---
ts: 2026-10-29T03:50:27Z
agent: opus-cc
branch: dev
type: feat
tasks: [T-007]
files: [src/remixer/bench/stress.py, src/remixer/bench/report.py, src/remixer/bench/cli.py, src/remixer/gpu/separate.py, src/remixer/gpu/cli.py, src/remixer/guards.py, tests/test_bench.py]
---

## What changed

remixer bench stress: --ramp (each lane alone at 25/50/75/100% of its budget, then all lanes together; knee = highest level still gaining >= 3%), --sustain 60m (all lanes at the knee; GPU runs the separation queue then heavy mode), lanes run as CLI subprocesses (separate --corpus-cycle/--loop, render, npu --parallel); telemetry tagged per step; acquires gpu, cpu, npu locks in order (--wait-locks). remixer bench report: per-run reports/peak/<ts>/ (summary.json, steps.json, telemetry parquet, PNG charts, dashboard.html) and cumulative docs/PEAK_REPORT.md (peak per stage, maxima, tuning rounds with 3% convergence rule, every configuration tried, knees, verdict). Guard interventions now also logged to data/state/guard_interventions.jsonl. separate --corpus-cycle for benchmarking without writing.

## Why

T-007.

## How to verify

uv run pytest tests/test_bench.py; uv run remixer bench stress --ramp --lanes gpu --step-seconds 90s

## Next / handoff

gpt-sol: bench drives your lanes via 'remixer render --workers W --seconds S --output D' (reads audio_seconds_per_second) and 'remixer npu --devices NPU GPU.0 --parallel' (sums inferences_per_second). Please keep those JSON keys stable. The combined run (T-018) needs the cpu and npu locks; release them when your peak sequence finishes.

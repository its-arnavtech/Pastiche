---
ts: 2026-10-29T05:09:41Z
agent: gpt-sol
branch: dev
type: fix
tasks: [T-013, T-007]
files: [src/remixer/bench/stress.py, tests/test_bench.py]
---

## What changed

Minimal bench integration: CPU ramp ceiling reads the render-worker recommendation from data/cpu-peak/tuning/tuning.json, capped by profile resources. Missing/incomplete tuning retains configured behavior. Added one integration test proving an explicit12-worker recommendation drives the built command.

## Why

T-013 definition of done requires its measured output to be consumed by bench stress; keeps requested worker metadata consistent with the calibrated16-worker combined budget.

## How to verify

uv run pytest tests/test_bench.py

## Next / handoff

opus-cc:bench now consumes the existing CPU artifact;GPU/NPUbuilders and JSONresultkeys unchanged. CPUandNPUlocksarefree.

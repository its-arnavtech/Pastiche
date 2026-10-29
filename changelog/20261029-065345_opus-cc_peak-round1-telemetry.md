---
ts: 2026-10-29T06:53:45Z
agent: opus-cc
branch: dev
type: perf
tasks: [T-018, T-007]
files: [src/remixer/bench/stress.py, src/remixer/bench/report.py, src/remixer/telemetry/sampler.py, src/remixer/telemetry/win_engines.py, src/remixer/telemetry/dashboard.py, tests/test_bench.py, docs/decisions/0022-peak-tuning-rounds.md]
---

## What changed

Round 1 (ramp + 60-min all-lane sustain) done. Heavy GPU steps now report model-pass audio-s/s (round 1 sustain: 58.6, same as light ramp). Telemetry records the effective CPU clock via PDH % Processor Performance and drops invalid idle-dGPU power readings. Decision 0022: tuning rounds use 15-minute sustains, one variable at a time.

## Why

Under the combined sustain render fell to 2.4 rendered audio-s/s and NPU+iGPU to 14k inferences/s while GPU held 94 %; the GPU is thermally capped (87 C, 54 of 90 W). The effective CPU clock is needed to tell thermal sharing apart from core contention.

## How to verify

uv run pytest tests/test_bench.py; reports/peak/20261029-001335/summary.json

## Next / handoff

opus-cc: re-embed under logmel-f32-v2 (gpt-sol's fix), retrain taste, then tuning rounds. Includes gpt-sol's tuning.json consumption hunk in stress.py/test_bench.py (their entry 20261029-050941).

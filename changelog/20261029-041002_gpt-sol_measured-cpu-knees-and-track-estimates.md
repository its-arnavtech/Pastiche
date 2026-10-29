---
ts: 2026-10-29T04:10:02Z
agent: gpt-sol
branch: dev
type: perf
tasks: [T-008, T-009, T-010, T-011, T-012, T-013]
files: [src/remixer/corpus, src/remixer/cpu, src/remixer/npu/scorer.py, src/remixer/synth/lab.py, tools/corpus, tests/cpu, tests/npu, docs/decisions/0007-track-harmony-and-arrangement-variety.md, docs/reports/cpu-lane.md]
---

## What changed

All four CPU stages met two-round<3%convergence; selected workers/chunk:corpus16/4,analysis12/1,render16/1,synth16/1. Original500 tracks score100%stem-supported key and0.276BPM MAE, with51%mix-only key retained. Added versioned eight-progression/four-drum-style generation while preserving legacy identities, selected-source provenance, source overwrite rejection, portable feeder/reserve budgets, retry-safe checkpoints, nonempty async timing, and real full-stage warm-ups. First corpus600s sustain90.87%hostCPU;analysis600s sustain90.98%hostCPU. NPU+iGPU concurrent600s:145477/92174embeddings/s.

## Why

Finish the complete assigned stages with measured accuracy, scaling and real sustained load; keep baseline limitations and physical overlap evidence visible.

## How to verify

31 focused CPU/NPU tests passed; full rerun in progress after short-duration async scheduling fix and warm-up handling. Hardware data:data/cpu-peak/tuning/tuning.json,data/cpu-peak/sustain/sustain.json,data/npu/dual/benchmark.json.

## Next / handoff

Continue render/evolution600s sustains and24arrangement validation;align GPU telemetry;refresh report,marktasksdone,commitonlyownedpaths,pushdev,andreleaseCPU/NPUlocksforcoordinator combinedT-018.

---
ts: 2026-10-29T14:13:54Z
agent: gpt-sol
branch: dev
type: bench
tasks: [T-008, T-009, T-010, T-011, T-012, T-013, T-030]
files: [docs/reports/cpu-lane.md, docs/reports/cpu-lane-scaling.png, docs/decisions/0007-track-harmony-and-arrangement-variety.md, tools/corpus/report.py, tools/corpus/refine_track_estimates.py, tools/corpus/upgrade_bass_features.py, src/remixer/cpu/analyze.py, src/remixer/cpu/cli.py, tests/cpu/test_analyze.py]
---

## What changed

Completed T008-T013 and measured four >=600-second CPU sustains, two convergence confirmations per stage, P/E affinity comparisons, full-budget Intel overlap and forced byte-identical 30-second rendering. Generated 500 legacy tracks (29.94 hours) plus 24 varied-arrangement validation tracks; original track key 100 percent and BPM MAE 0.275584, varied key 91.67 percent and BPM MAE 0.285074. Preserved blind mix baselines and versioned source identities. Report includes qualified worker knees, aggregate disk/RAM counters, GPU overlap, available thermals and raw evidence paths.

## Why

Finish the assigned CPU and Intel lanes with measured reproducible evidence and explicit limits, while preserving the coordinator resource budget and private-library provenance.

## How to verify

Full suite 239 passed, 1 skipped, 1 deselected in90.12s with CUDA hidden and one math thread. Trained GELU/bias export matches PyTorch and NumPy; FP32 CLAP forward is finite; all-NaN production checkpoint is rejected. Original storm recipe forced twice matches SHA256 bd96839b4c270a6ac271eaff5ae6684bfe1d3b9671f8f004eb4f7627462043b6. Plot visually checked; git diff --check passes.

## Next / handoff

All six owned tasks done and CPU/NPU locks released. Coordinator owns T018 combined-engine certification and T022 new-version re-embedding/retraining after the corrupt upstream artifact. No new user blocker; existing optional actions remain in docs/NEEDS_USER.md.

---
ts: 2026-10-29T03:20:06Z
agent: gpt-sol
branch: dev
type: fix
tasks: [T-008, T-009, T-010, T-011, T-012, T-013]
files: [src/remixer/corpus/generate.py, src/remixer/cpu/runtime.py, src/remixer/cpu/tuner.py, src/remixer/npu/scorer.py, src/remixer/synth/lab.py, tools/corpus, docs/decisions/0006-windows-checkpoint-reader-sharing.md]
---

## What changed

Added bounded retry for transient Windows delete-sharing failures during atomic replacement; regression reproduces two denied replacements then success. Added bounded async Intel dual-engine feeding, complete evolution/render storm sustains, timestamped sensor and CPU sample series, and artifact-driven CPU report tooling. Restarted incomplete GPU.0/CPU baseline; NPU600s result retained.

## Why

A concurrent checkpoint read stopped the original iGPU run at248s; atomic checkpoints must tolerate short Windows reader holds. Full stage sustains must exercise evolution and cross-source recipes.

## How to verify

uv run pytest tests/cpu/test_corpus.py tests/npu/test_scorer.py:6passed; previous fullsuite42passed andfocused17passed; all2500 corpus analysis outputs complete with zeroerrors.

## Next / handoff

Tuning active through allworker/chunk/P-E configurations, then600s perstage. Recovered Intel baseline followed by600s simultaneous NPU/iGPU. Accuracy confusions under investigation; preserve reported baseline rather than infer success.

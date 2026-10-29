---
ts: 2026-10-29T04:10:49Z
agent: opus-cc
branch: dev
type: perf
tasks: [T-005, T-004, T-007]
files: [src/remixer/gpu/embed.py, src/remixer/gpu/cli.py, src/remixer/adapters/local_compute.py, src/remixer/bench/stress.py, tests/test_embed.py, docs/decisions/0010-gpu-batch-sizing-sysmem-fallback.md, docs/decisions/0011-clap-embeddings-gpu-frontend.md, docs/decisions/0012-gpu-lane-process-priority.md, docs/licenses.md]
---

## What changed

GPU-lane processes (separate, embed) raise themselves to ABOVE_NORMAL priority. CLAP embedding worker (remixer embed): per-stem and per-5s-window 512-d vectors, GPU resample + GPU log-mel matched to ClapFeatureExtractor, fp16, cross-stem window batching with VRAM calibration, .npy checkpoints + catalog rows + hnswlib index. Bench refreshes its locks every step. Decisions 0010-0012, docs/licenses.md.

## Why

Isolated GPU ramp under gpt-sol's CPU sustain collapsed to 8-24% GPU util (feeders starved); with the priority boost the same load gives 56x realtime. T-005.

## How to verify

uv run pytest tests/test_embed.py; uv run remixer separate --corpus-cycle --batch 10 --duration 90 while the CPU lane runs

## Next / handoff

Decision numbers 0008/0009 were taken by gpt-audit and gpt-sol concurrently; mine are 0010-0012. Use 'ls docs/decisions' right before picking a number.

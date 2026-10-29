---
ts: 2026-10-29T04:33:01Z
agent: opus-cc
branch: dev
type: feat
tasks: [T-019, T-018]
files: [src/remixer/gpu/musicgen.py, src/remixer/gpu/cli.py, docs/licenses.md, docs/ENVIRONMENT.md, docs/NEEDS_USER.md]
---

## What changed

remixer musicgen: MusicGen-small fp16 inference loop as extra GPU load (outputs discarded; CC-BY-NC-4.0 recorded in docs/licenses.md, local benchmarking only). ENVIRONMENT: torch/CUDA/cuDNN/driver facts. NEEDS_USER: merge-worktree cleanup and one uv sync once agents are idle.

## Why

T-019 stretch; Step 0 torch facts.

## How to verify

uv run remixer musicgen --duration 60

## Next / handoff

opus-cc has queued the T-018 combined run: it starts after the full-corpus separation + embedding finish and waits up to 3 h for the cpu and npu locks (bench stress --ramp --sustain 60m). gpt-sol: just release cpu/npu when your sustains end; the bench picks them up within 30 s.

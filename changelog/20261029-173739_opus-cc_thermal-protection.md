---
ts: 2026-10-29T17:37:39Z
agent: opus-cc
branch: dev
type: fix
tasks: [T-018]
files: [src/remixer/bench/stress.py, src/remixer/bench/cli.py, src/remixer/telemetry/win_engines.py, src/remixer/telemetry/sampler.py, tests/test_bench.py, docs/decisions/0025-thermal-protection-after-shutdowns.md, docs/NEEDS_USER.md]
---

## What changed

Two T-018 attempts ended in unexpected laptop shutdowns (event 6008) when the CPU render ramp started after the GPU ramp. Added: ACPI thermal-zone telemetry (_TZ.THRM = CPU package, readable without admin), bench load caps and a thermal watchdog that suspends CPU/NPU lanes at a 97 C CPU-zone median or GPU 90 C, cooldown to 82 C between steps, and a --cool preset (cpu<=8, gpu batch<=8 light only, NPU without iGPU). Decision 0025; NEEDS_USER item 4.

## Why

User: the laptop kills itself; adjust parameters and retry.

## How to verify

uv run pytest tests/test_bench.py

## Next / handoff

opus-cc: T-018 rerun with --cool, then relax one cap per tuning round.

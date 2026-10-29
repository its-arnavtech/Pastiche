---
ts: 2026-10-29T22:03:32Z
agent: wrapup
branch: dev
type: feat
tasks: [T-031]
files: [src/remixer/presets.py, src/remixer/config.py, src/remixer/guards.py, src/remixer/cli.py, profile.yaml, docs/decisions/0030-stable-preset-default.md]
---

## What changed

Stable (capped) preset is the default: 8 CPU workers, light Demucs batch<=8, NPU only, watchdog on, CPU cutoff 93 C. Old behaviour behind explicit --unleashed with warning.

## Why

Uncapped runs shut the laptop down twice; the 97 C cutoff could never fire (sensor max 95.9 C).

## How to verify

uv run pytest tests/test_presets.py tests/test_core.py tests/test_bench.py; remixer info shows mode stable, cpu_workers 8

## Next / handoff

Acceptance doc, demo.

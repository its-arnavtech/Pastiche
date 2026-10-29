---
ts: 2026-10-29T02:40:21Z
agent: gpt-sol
branch: dev
type: feat
tasks: [T-009, T-010, T-012]
files: [pyproject.toml, uv.lock]
---

## What changed

uv add pedalboard pyloudnorm openvino: Rubber Band DSP, BS.1770 loudness meter, and Intel device inference runtime.

## Why

Required by the CPU DSP and NPU assignments. Licenses: Pedalboard GPL-3.0, pyloudnorm MIT, OpenVINO Apache-2.0; local POC only.

## How to verify

uv add completed; imports verified in subsequent CPU and NPU tests.

## Next / handoff

Implement analysis, deterministic rendering, and OpenVINO scorer.

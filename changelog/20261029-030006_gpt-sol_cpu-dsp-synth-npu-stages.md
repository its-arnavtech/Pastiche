---
ts: 2026-10-29T03:00:06Z
agent: gpt-sol
branch: dev
type: feat
tasks: [T-009, T-010, T-011, T-012, T-013]
files: [src/remixer/cpu, src/remixer/synth, src/remixer/npu, src/remixer/corpus/cli.py, src/remixer/adapters/cpu_topology.py, tests/cpu, tests/npu, tools/corpus/peak_run.py, docs/decisions/0005-cpu-measurement-and-intel-placement.md]
---

## What changed

Added mmap/streaming analysis with reference-verified BS.1770 LUFS and durable queue support; seeded recipes and Rubber Band time/pitch rendering; resumable evolutionary synth with replaceable fitness; static OpenVINO scorer with numeric validation, Intel-only GPU placement and explicit CPU fallback; worker/chunk/P-E affinity sweeps with knee and convergence; shared CLI registration and autonomous peak runner.

## Why

Implements all assigned CPU/NPU stages against portable interfaces and preserves GPU feeders and atomic checkpoints.

## How to verify

uv run pytest:42 passed in88.50s. Determinism, exact stems, tempo70-175range samples, LUFS reference, octave shift, queue resume, staticIR CPU parity and NVIDIA exclusion covered; full corpus analysis and ten-minute device sustains active.

## Next / handoff

opus-cc:import remixer.cpu.tuner.measure/stage_unit or CLI cpu tune/sustain; tuning JSON at data/cpu-peak/tuning/tuning.json once ready. CPU/NPU locks held by gpt-sol; live analysis16workers plus NPU sustain. All-engines peak can overlap these stages.

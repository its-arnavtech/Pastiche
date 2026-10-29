---
ts: 2026-10-29T14:35:55Z
agent: opus-cc
branch: dev
type: bench
tasks: [T-018]
files: [docs/ENVIRONMENT.md, docs/NEEDS_USER.md]
---

## What changed

T-018 combined all-engines peak run starting now: ramp (GPU, CPU, NPU/iGPU isolated, then all at 25/50/75/100 %) then 60-minute sustain, with pinned lane core sets (decision 0024) and GPU above-normal priority. Power mode: Best performance on AC (user-set, recorded in docs/ENVIRONMENT.md). gpu, cpu, npu locks will be held by opus-cc for the whole run.

## Why

Brief step 6 / user step 4. All other agents idle.

## How to verify

reports/peak/<ts>/ when finished; docs/PEAK_REPORT.md

## Next / handoff

Everyone: do not start CPU/GPU/NPU work until opus-cc posts the result entry; it would distort the benchmark.

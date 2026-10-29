---
ts: 2026-10-29T03:58:37Z
agent: gpt-sol
branch: dev
type: handoff
tasks: [T-007, T-018, T-013]
files: [docs/reports/cpu-lane.md]
---

## What changed

CPU/NPU full peak is live. Four stages at600s each follow completed worker/chunk/P-E sweeps; corpus sustain16workers averaged90.87%hostCPU. Both Intel engines held through CPU sequence with one host loop; iGPU PDH measured98.9% compute. GPU context sampling currently shows NVIDIAidle0% (NVML Unknown at idle; Windowscounter verified).

## Why

Need real NVIDIA overlap to certify each required CPU stage sustained alongside the GPU lane. Do not launch duplicate CPU/NPU jobs on top of these owner locks.

## How to verify

data/cpu-peak/runner.json;data/cpu-peak/sustain/sustain.json;data/npu/peak-hold/checkpoint.json;data/cpu-peak/gpu-overlap.jsonl.

## Next / handoff

opus-cc:GPU-only bench/Demucs may run concurrently now;CPU+Intel physical lanes already loaded by gpt-sol. GPUtiming/telemetry will be aligned to CPU stage epochs;repeat CPU stages if needed for full10-minute GPUoverlap. Current CPU/NPU locks stay with gpt-sol during sustain.

---
ts: 2026-10-29T04:16:02Z
agent: gpt-audit
branch: dev
type: fix
tasks: [T-020]
files: [docs/audits/gpu-env-audit.md, tools/audit/gpu_probe.py, docs/decisions/0008-isolated-gpu-environment-audit.md, .gitignore]
---

## What changed

Diagnosed misleading CPython missing-file quote; reproduced it with an isolated copied launcher. Documented working shared interpreter, CUDA torch provenance, Intel OpenVINO attribution, and safe conditional repair. Added lease-aware isolated CUDA/Demucs probe.

## Why

Avoid replacing a live environment or blaming CPU-only torch when the current lock and installation already select CUDA.

## How to verify

Shared launcher and base Python both 3.11.15; config contains no quotes; copied missing-path launcher reproduces quote. Full isolated repository suite: 76 passed, exit 0. Isolated torch 2.14.1+cu130 / CUDA 13.0 / torchaudio 2.11.0+cu130: CUDA available, RTX 4060 identified, 3776 matmuls in 20.078 s with repeated 99-100% nvidia-smi utilization. Pretrained htdemucs separated synthetic stereo into finite [1,4,2,44100] stems on cuda:0 in 1.578 s. Audit GPU lease released; shared config hash unchanged. Raw results data/audit/gpu-probe.json.

## Next / handoff

opus-cc: keep existing explicit pytorch-cu130 torch mapping and shared .venv; retain your concurrent GPU scheduling and VRAM-sizing fixes (decisions 0010/0012). CPU feeder starvation, not CPU-only torch or Intel CUDA routing, explains low GPU duty cycle. A process-local UV_CACHE_DIR under data/audit fixes the reproduced restricted-cache failure. Main env is active: defer any repair; exact idle-gated commands are in the audit. After the T-005 worker exited, its unchanged lease remained; two host checks confirmed no CUDA worker/process, then the exact abandoned lease was recovered per decision 0008 before audit acquisition. Lease PID alone is insufficient because it can identify the acquisition CLI. Both CUDA probe and suite now pass; no main dependency change is needed.

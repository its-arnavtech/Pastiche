---
id: T-012
title: NPU/iGPU OpenVINO lane
status: in_progress
owner: gpt-sol
branch: dev
lane: npu
depends_on: [T-005]
owns_paths: [src/remixer/npu/]
claimed_at: 2026-10-29T02:45:54Z
heartbeat_at: 2026-10-29T02:45:54Z
priority: P1
---

## Goal

Taste scorer and similarity scoring exported to OpenVINO, run on NPU and iGPU in parallel with GPU work; CPU fallback.

## Definition of done

Inferences/sec per device logged; falls back cleanly when export fails.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner gpt-sol)
- 2026-10-29T02:45:54Z gpt-sol: claimed

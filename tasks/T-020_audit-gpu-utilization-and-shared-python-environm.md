---
id: T-020
title: Audit GPU utilization and shared Python environment
status: done
owner: gpt-audit
branch: dev
lane: none
depends_on: []
owns_paths: [docs/audits/gpu-env-audit.md, tools/audit, docs/decisions/0008-isolated-gpu-environment-audit.md, .gitignore]
claimed_at: 2026-10-29T03:56:47Z
heartbeat_at: 2026-10-29T04:25:35Z
priority: P0
---

## Goal

Diagnose shared Python launcher and GPU usage read-only; validate isolated CUDA and hand off repair.

## Definition of done

Evidence documented, isolated CUDA matmul and Demucs tested when GPU lane available, shared environment preserved.

## Progress and handoff log

- 2026-10-29T03:56:11Z gpt-audit: created
- 2026-10-29T03:56:48Z gpt-audit: claimed
- 2026-10-29T04:15:18Z gpt-audit: Read-only diagnosis complete; shared Python and CUDA wheel healthy. Isolated test suite running; CUDA probe waiting for Opus T-005 GPU lease.
- 2026-10-29T04:23:44Z gpt-audit: Full isolated suite passed. Recovered verified abandoned T-005 lease after two host process/GPU checks and unchanged contents; own isolated CUDA probe now holds GPU.
- 2026-10-29T04:25:35Z gpt-audit: done: Audit complete: full isolated suite76passed; RTX4060 CUDA matmul repeatedly99-100%; pretrained Demucs finite CUDA stems. Shared .venv preserved, CUDA index already correct, CPU feeder starvation confirmed by Opus comparison; safe conditional repair commands and orphan-lease recovery evidence documented.

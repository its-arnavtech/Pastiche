---
id: T-018
title: Combined all-engines run and final peak report
status: in_progress
owner: opus-cc
branch: dev
lane: none
depends_on: [T-004, T-005, T-006, T-007, T-009, T-010, T-012, T-013]
owns_paths: [docs/PEAK_REPORT.md, reports/peak/]
claimed_at: 2026-10-29T05:07:30Z
heartbeat_at: 2026-10-29T05:07:30Z
priority: P0
---

## Goal

Acquire gpu, cpu, npu locks; ramp then 60-minute sustain with all lanes; tune and rerun until two rounds improve < 3%.

## Definition of done

docs/PEAK_REPORT.md with a table of every configuration and a verdict.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner opus-cc)
- 2026-10-29T05:07:30Z opus-cc: claimed

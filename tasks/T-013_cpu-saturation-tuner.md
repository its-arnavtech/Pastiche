---
id: T-013
title: CPU saturation tuner
status: in_progress
owner: gpt-sol
branch: dev
lane: cpu
depends_on: [T-009, T-010]
owns_paths: [src/remixer/cpu/tuner.py]
claimed_at: 2026-10-29T02:48:11Z
heartbeat_at: 2026-10-29T02:48:11Z
priority: P1
---

## Goal

Find worker counts / chunk sizes that hold CPU near 100% without starving GPU feeders.

## Definition of done

Tuner output consumed by bench stress; results in the peak report.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner gpt-sol)
- 2026-10-29T02:48:11Z gpt-sol: claimed

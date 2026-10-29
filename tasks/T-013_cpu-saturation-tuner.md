---
id: T-013
title: CPU saturation tuner
status: todo
owner: gpt-sol
branch: dev
lane: cpu
depends_on: [T-009, T-010]
owns_paths: [src/remixer/cpu/tuner.py]
claimed_at:
heartbeat_at:
priority: P1
---

## Goal

Find worker counts / chunk sizes that hold CPU near 100% without starving GPU feeders.

## Definition of done

Tuner output consumed by bench stress; results in the peak report.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner gpt-sol)

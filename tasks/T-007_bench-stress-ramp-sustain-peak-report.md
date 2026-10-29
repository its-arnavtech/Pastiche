---
id: T-007
title: bench stress ramp + sustain + peak report
status: todo
owner: opus-cc
branch: dev
lane: none
depends_on: [T-004, T-006]
owns_paths: [src/remixer/bench/, docs/PEAK_REPORT.md, reports/peak/]
claimed_at:
heartbeat_at:
priority: P0
---

## Goal

`remixer bench stress --ramp` (25/50/75/100% per lane, find the knee) and `--sustain 60m` (all lanes, best config) writing reports/peak/<ts>/ and docs/PEAK_REPORT.md.

## Definition of done

Report contains per-stage peak throughput, per-engine utilization, VRAM/RAM maxima, temps, throttle events, best worker counts and batch sizes, verdict.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner opus-cc)

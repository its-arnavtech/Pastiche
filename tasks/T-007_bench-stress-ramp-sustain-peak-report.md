---
id: T-007
title: bench stress ramp + sustain + peak report
status: done
owner: opus-cc
branch: dev
lane: none
depends_on: [T-004, T-006]
owns_paths: [src/remixer/bench/, docs/PEAK_REPORT.md, reports/peak/]
claimed_at: 2026-10-29T03:50:28Z
heartbeat_at: 2026-10-29T20:23:27Z
priority: P0
---

## Goal

`remixer bench stress --ramp` (25/50/75/100% per lane, find the knee) and `--sustain 60m` (all lanes, best config) writing reports/peak/<ts>/ and docs/PEAK_REPORT.md.

## Definition of done

Report contains per-stage peak throughput, per-engine utilization, VRAM/RAM maxima, temps, throttle events, best worker counts and batch sizes, verdict.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner opus-cc)
- 2026-10-29T03:50:28Z opus-cc: claimed
- 2026-10-29T05:07:30Z opus-cc: handoff: bench stress ramp/sustain/report working; T-018 run in progress
- 2026-10-29T20:23:27Z opus-cc: done: Bench stress ramp/sustain/report used end to end by T-018; report extended with pass, starvation and thermal-pause columns.

---
id: T-009
title: Analysis workers (tempo, key, loudness, window features)
status: in_progress
owner: gpt-sol
branch: dev
lane: cpu
depends_on: [T-002]
owns_paths: [src/remixer/cpu/analyze.py]
claimed_at: 2026-10-29T02:37:23Z
heartbeat_at: 2026-10-29T02:37:23Z
priority: P1
---

## Goal

Per track and per stem: tempo and beat grid, key, LUFS, energy curve, 5-second window features, in a process pool sized from config/resources.yaml.

## Definition of done

Correct on synthetic ground truth; resumable via job queue; logs items/sec.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner gpt-sol)
- 2026-10-29T02:37:23Z gpt-sol: claimed

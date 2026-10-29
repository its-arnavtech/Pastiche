---
id: T-010
title: DSP assembler and render storm
status: in_progress
owner: gpt-sol
branch: dev
lane: cpu
depends_on: [T-009]
owns_paths: [src/remixer/cpu/assemble.py, src/remixer/cpu/render.py]
claimed_at: 2026-10-29T02:42:11Z
heartbeat_at: 2026-10-29T02:42:11Z
priority: P1
---

## Goal

Recipe-based assembler (stem picks, time ranges, stretch/shift, loudness match, seed) and a render storm load generator.

## Definition of done

Same recipe + seed gives a byte-identical render; renders/sec logged.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner gpt-sol)
- 2026-10-29T02:42:12Z gpt-sol: claimed

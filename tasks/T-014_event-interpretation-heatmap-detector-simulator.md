---
id: T-014
title: Event interpretation + heatmap detector + simulator
status: in_progress
owner: cursor-opus
branch: feature/skip-analytics
lane: none
depends_on: [T-001]
owns_paths: [src/remixer/analytics/, tests/analytics/]
claimed_at: 2026-10-29T02:44:59Z
heartbeat_at: 2026-10-29T02:53:17Z
priority: P0
---

## Goal

Playback event schema and interpretation (skip bursts, undo, replay, next/previous) and the 5-second-window skip heatmap detector from spec section 5, plus a synthetic event simulator.

## Definition of done

Tests with known skip patterns including undo and burst cases pass.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner cursor-opus)
- 2026-10-29T02:44:59Z cursor-opus: claimed
- 2026-10-29T02:53:17Z cursor-opus: event schema, interpretation (burst/undo/late-return/replay/next/previous), heatmap + detector with tests; simulator next

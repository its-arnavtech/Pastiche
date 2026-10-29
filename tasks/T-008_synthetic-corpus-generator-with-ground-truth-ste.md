---
id: T-008
title: Synthetic corpus generator with ground-truth stems
status: in_progress
owner: gpt-sol
branch: dev
lane: cpu
depends_on: [T-001]
owns_paths: [src/remixer/corpus/]
claimed_at: 2026-10-29T02:33:02Z
heartbeat_at: 2026-10-29T02:33:02Z
priority: P0
---

## Goal

Generate a synthetic library (>=200 tracks) with known drums/bass/vocals/other stems, plus pitch/tempo-augmented variants with new content hashes. Rows flagged synthetic/augmented.

## Definition of done

`remixer corpus generate --n 200` is deterministic by seed; ground-truth stems stored for SDR checks.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner gpt-sol)
- 2026-10-29T02:33:03Z gpt-sol: claimed

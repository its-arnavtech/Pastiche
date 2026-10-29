---
id: T-008
title: Synthetic corpus generator with ground-truth stems
status: todo
owner: gpt-sol
branch: dev
lane: cpu
depends_on: [T-001]
owns_paths: [src/remixer/corpus/]
claimed_at:
heartbeat_at:
priority: P0
---

## Goal

Generate a synthetic library (>=200 tracks) with known drums/bass/vocals/other stems, plus pitch/tempo-augmented variants with new content hashes. Rows flagged synthetic/augmented.

## Definition of done

`remixer corpus generate --n 200` is deterministic by seed; ground-truth stems stored for SDR checks.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner gpt-sol)

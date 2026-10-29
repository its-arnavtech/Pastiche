---
id: T-002
title: SQLite catalog + durable job queue
status: todo
owner: opus-cc
branch: dev
lane: none
depends_on: [T-001]
owns_paths: [src/remixer/adapters/sqlite_catalog.py, src/remixer/adapters/sqlite_queue.py]
claimed_at:
heartbeat_at:
priority: P0
---

## Goal

Catalog schema for tracks, stems, windows, recipes, recipe_stems, renders, rating_events, playback_events, stem_exposure, insights, jobs. Durable job queue with lease/ack/retry, safe across processes.

## Definition of done

Jobs survive a forced kill (lease expiry returns them); idempotent enqueue by (kind, content hash, model version); tests cover concurrency from several processes.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner opus-cc)

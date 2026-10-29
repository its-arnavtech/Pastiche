---
id: T-003
title: Guards: disk, battery, thermal
status: done
owner: opus-cc
branch: dev
lane: none
depends_on: [T-001]
owns_paths: [src/remixer/guards.py]
claimed_at: 2026-10-29T02:30:53Z
heartbeat_at: 2026-10-29T02:44:45Z
priority: P0
---

## Goal

remixer.guards: unleashed by default (log thermals, battery, throttle reasons only); disk floor 10 GB pauses writers and purges data-dir caches; --safe restores conservative guards.

## Definition of done

Tests for both modes; every long-running worker calls guards.check().

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner opus-cc)
- 2026-10-29T02:30:53Z opus-cc: claimed
- 2026-10-29T02:44:45Z opus-cc: done: landed in core-skeleton commit; tests/test_core.py

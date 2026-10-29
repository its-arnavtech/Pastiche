---
id: T-016
title: Player UI with event logging
status: done
owner: cursor-opus
branch: feature/skip-analytics
lane: none
depends_on: [T-014]
owns_paths: [web/, tests/web/]
claimed_at: 2026-10-29T03:18:55Z
heartbeat_at: 2026-10-29T03:29:40Z
priority: P1
---

## Goal

FastAPI + plain HTML/JS player with the controls in spec section 5 and user-initiated rating controls; append-only event log.

## Definition of done

Every control logs the right event; contract tests pass.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner cursor-opus)
- 2026-10-29T03:18:55Z cursor-opus: claimed
- 2026-10-29T03:29:40Z cursor-opus: done: Done: player + inbox + mock backend, 20 Playwright tests green. Handoff: real backend implements the routes in decision 0009.

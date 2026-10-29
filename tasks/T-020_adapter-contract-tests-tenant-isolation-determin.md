---
id: T-020
title: Adapter contract tests (tenant isolation, determinism)
status: in_progress
owner: cursor-opus
branch: feature/skip-analytics
lane: none
depends_on: [T-001, T-002, T-014]
owns_paths: [tests/contracts/]
claimed_at: 2026-10-29T03:30:34Z
heartbeat_at: 2026-10-29T03:30:34Z
priority: P2
---

## Goal

One contract suite that every adapter profile must pass (POC 2 spec sections 6, 8, 9): BlobStore, Catalog, EventSink, JobQueue, VectorIndex, ComputeBackend behavior; two-tenant isolation that fails if tenant A can read tenant B's data; determinism of content keys and of the analytics/fatigue pipeline read back through the EventSink. Local profile now; commercial profiles register a factory later.

## Definition of done

tests/contracts pass under the local profile on plain CI; adding a profile is one registry entry; handoff note to opus-cc.

## Progress and handoff log

- 2026-10-29T03:30:34Z cursor-opus: created
- 2026-10-29T03:30:34Z cursor-opus: claimed

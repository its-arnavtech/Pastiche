---
ts: 2026-10-29T03:35:12Z
agent: cursor-opus
branch: feature/skip-analytics
type: feat
tasks: [T-020]
files: [tests/contracts/, src/remixer/analytics/events.py, src/remixer/analytics/simulate.py, src/remixer/analytics/scale.py, tests/analytics/test_events.py, docs/decisions/0010-adapter-contract-suite.md]
---

## What changed

tests/contracts: 39 contract tests that every adapter profile must pass, parametrized over a PROFILES registry (local-max now, built through remixer.adapters.build). BlobStore (content addressing, idempotent put, namespaces, delete, put_file copies and never touches a read-only source), Catalog (upsert insert/update, key-only upsert no-op, insert ids, parameter binding, synthetic flag), EventSink (append-only, no rewrite, separate streams, where filter, exact T-014 round trip via Event.to_row/from_row), JobQueue (idempotent enqueue, exclusive lease, priority then FIFO, bounded retries, fail without retry, release does not count, expired lease takeover, extend), VectorIndex (self is nearest, k clipping, save/reopen, named indexes), ComputeBackend (cpu always present, positive budgets), durability across reopen for each. Tenant isolation in both directions across events, catalog, ratings, jobs, blobs and vectors, with a test proving the check fails when two handles share data. Determinism: heatmap, candidates, insights, signals, fatigue and seeded selection identical whether events are read directly, from one append, or from shuffled appends into another tenant; content-only blob keys; same lease order. Analytics: Event.to_row/from_row (scale.py now uses it), client_info.seq stamped by the simulator and used by sort_events to break equal wall-time ties. Decision 0010.

## Why

AGENTS.md assigns contract tests to cursor-opus; POC 2 spec sections 6, 8, 9 require one suite both profiles pass, tenant isolation tests that fail on a leak, and identical results across profiles. The seq tie-break is needed because sinks need not preserve append order (a probe without seq changed the heatmap after shuffled storage).

## How to verify

uv run pytest tests/contracts (39 passed, ~2 s); whole repo uv run pytest: 224 passed, 1 deselected (2M scale test). Detector numbers unchanged: 20 seeds precision 1.0000 recall 1.0000.

## Next / handoff

opus-cc: when the commercial adapters exist, add one PROFILES entry in tests/contracts/conftest.py mapping tenant_id to the commercial tenancy; every test then runs against it. Gaps to add once the interfaces support them: tenant deletion (spec section 4), LLMClient, torch_device.

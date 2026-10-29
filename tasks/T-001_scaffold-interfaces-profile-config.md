---
id: T-001
title: Scaffold, interfaces, profile config
status: in_progress
owner: opus-cc
branch: dev
lane: none
depends_on: []
owns_paths: [src/remixer/interfaces.py, src/remixer/config.py, src/remixer/adapters/, profile.yaml, pyproject.toml]
claimed_at: 2026-10-29T02:30:52Z
heartbeat_at: 2026-10-29T02:30:52Z
priority: P0
---

## Goal

uv project (Python 3.11), package src/remixer with PROJECT_NAME constant, the seven interfaces (BlobStore, Catalog, EventSink, VectorIndex, JobQueue, ComputeBackend, LLMClient) with local adapters, profile.yaml loader, `remixer` CLI entry point.

## Definition of done

`uv run remixer --help` works; interfaces importable; profile.yaml selects adapters; unit tests for config and adapters pass.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner opus-cc)
- 2026-10-29T02:30:52Z opus-cc: claimed

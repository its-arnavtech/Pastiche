---
ts: 2026-10-29T02:45:44Z
agent: cursor-opus
branch: feature/skip-analytics
type: decision
tasks: [T-014, T-015, T-016]
files: [pyproject.toml, uv.lock, docs/decisions/0004-cursor-opus-paths-and-packaging.md]
---

## What changed

Bare pyproject.toml (uv init --bare, no build backend) with optional groups: analytics = numpy>=1.26, duckdb>=1.0, pyarrow>=15; web-test = playwright>=1.45; dev group = pytest, hypothesis. pytest config: pythonpath src, 'scale' and 'web' markers, scale tests opt-in. Decision 0004: cursor-opus paths follow the brief (src/remixer/analytics, src/remixer/fatigue, web/), remixer stays a namespace package until T-001, single event envelope with optional payload for rating and insight events.

## Why

T-001 (pyproject, package init) is not on dev yet; cursor-opus needs a place to declare optional deps and a test config without colliding with T-001.

## How to verify

uv sync --all-extras && uv run pytest

## Next / handoff

opus-cc: when merging, keep the T-001 pyproject and re-add the analytics and web-test optional groups, the dev group and the pytest settings (or take this file if T-001 has not landed). Then run uv lock.

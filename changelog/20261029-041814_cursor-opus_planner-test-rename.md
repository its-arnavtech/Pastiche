---
ts: 2026-10-29T04:18:14Z
agent: cursor-opus
branch: feature/recipe-planner
type: fix
tasks: [T-022]
files: [tests/planner/test_planner_scale.py]
---

## What changed

Renamed tests/planner/test_scale.py to tests/planner/test_planner_scale.py (supersedes the path in the planner-scale entry).

## Why

Tests are not packages, so basenames must be unique; it collided with tests/analytics/test_scale.py and broke collection of the full suite.

## How to verify

uv run pytest -o addopts='' -m 'not scale': 282 passed, 2 deselected; uv run pytest -o addopts='' -m scale tests/planner/test_planner_scale.py: 1 passed (47 s).

## Next / handoff

Handoff notes, task done, PR into dev.

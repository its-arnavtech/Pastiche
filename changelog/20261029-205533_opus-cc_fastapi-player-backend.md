---
ts: 2026-10-29T20:55:33Z
agent: opus-cc
branch: dev
type: feat
tasks: [T-016]
files: [src/remixer/server/__init__.py, src/remixer/server/app.py, src/remixer/cli.py, pyproject.toml, uv.lock, tests/web/conftest.py, tests/test_player_backend.py, docs/decisions/0029-fastapi-player-backend.md, docs/NEEDS_USER.md]
---

## What changed

Real FastAPI player backend (remixer serve) on the adapters: catalog tracks and recipe renders, blob-store audio with ranges, events into the playback Parquet stream (read by the nightly job), inbox from the nightly InsightState. Browser tests parametrized over mock + real backend; Edge fallback when Playwright's Chromium build is missing.

## Why

Decision 0016 asked for the real backend serving the mock's six routes, with cursor's tests passing against it.

## How to verify

tests/web: 42 passed (21 tests x mock and fastapi) on Edge 156; tests/test_player_backend.py 5 passed; full suite 411 passed, 0 failed, 0 skipped.

## Next / handoff

None required; optional playwright install chromium (NEEDS_USER item 3).

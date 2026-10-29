---
ts: 2026-10-29T04:26:51Z
agent: opus-cc
branch: merge/skip-analytics
type: merge
tasks: [T-014, T-015, T-016, T-021]
files: [src/remixer/analytics, src/remixer/fatigue, web, tests/analytics, tests/contracts, tests/fatigue, tests/web, pyproject.toml, uv.lock, docs/decisions, tasks/T-021_adapter-contract-tests-tenant-isolation-determin.md]
---

## What changed

Merged PR #1 (feature/skip-analytics, cursor-opus) into dev with --no-ff: analytics (events, interpretation, heatmap, simulator, scale), fatigue (credit, attribution, state, propagation, selection, insights), static player + inbox + mock backend, adapter contract suite. Renumbered at merge to remove collisions with dev: decisions 0006->0013, 0007->0014, 0008->0015, 0009->0016, 0010->0017 (file names, titles, the reference in analytics/events.py); task T-020 (adapter contracts) -> T-021 because T-020 on dev is gpt-audit's GPU audit. Historical changelog bodies keep the old numbers; read them through this map. uv.lock regenerated with uv lock.

## Why

Coordinator merge duty; DoD and tests met.

## How to verify

uv sync --extra analytics; uv run pytest -m 'not scale and not web' -> 212 tests, 0 failures, 1 skipped (Windows, after merge)

## Next / handoff

cursor-opus: on your next session rebase/merge dev; your decisions are now 0013-0017 and the contract task is T-021. Web tests (-m web) need 'uv sync --extra web-test' and 'playwright install chromium' (not run here). opus-cc will wire the real FastAPI backend later only if time allows; the mock backend stays the reference.

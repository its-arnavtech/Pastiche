---
ts: 2026-10-29T02:30:40Z
agent: opus-cc
branch: dev
type: feat
tasks: [T-001]
files: [AGENTS.md, CLAUDE.md, .cursor/rules/coordination.mdc, scripts/agentctl.py, tests/test_agentctl.py, tasks/, config/resources.yaml, docs/]
---

## What changed

Coordination system: AGENTS.md, CLAUDE.md, Cursor rule, scripts/agentctl.py (status, log, changelog, task new/claim/heartbeat/handoff/done/takeover/list, lock acquire/release/status) with tests, config/resources.yaml lane budgets (22 logical: 4 GPU feeders, 1 reserve, 17 CPU), 19 seeded tasks, specs in docs/specs, ENVIRONMENT, NEEDS_USER, decisions 0001-0003.

## Why

Other agents depend on the coordination system before writing code.

## How to verify

uv run --python 3.11 --no-project --with pytest pytest tests/test_agentctl.py; python scripts/agentctl.py status

## Next / handoff

gpt-sol: claim T-008 first (synthetic corpus unblocks everything). cursor-opus: branch feature/skip-analytics from dev and claim T-014. opus-cc continues with T-001..T-003 (pyproject + interfaces land next; until then use the stdlib-only agentctl).

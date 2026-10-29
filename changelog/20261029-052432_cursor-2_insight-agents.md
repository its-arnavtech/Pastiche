---
ts: 2026-10-29T05:24:32Z
agent: cursor-2
branch: cursor/insight-agents-442b
type: feat
tasks: [T-027]
files: [src/remixer/insights/, tests/insights/, web/mock_server.py, web/js/inbox.js, web/js/events.js, web/css/style.css, tests/web/test_inbox.py]
---

## What changed

Insight layer in src/remixer/insights/: LLMClient protocol and MockLLM; Analyst, Skeptic and Narrator as pure functions with schema-validated JSON and deterministic fallbacks; lifecycle proposed/shown/confirmed/dismissed/not_sure delivered only to the passive inbox (one new insight a day, 7-day not-sure delay, dismissal suppresses the window); bounded per-user threshold updates; detector pre-filter, input-hash cache, per-track batching and a 30-call daily budget. Wired into the existing mock inbox. No new dependencies.

## Why

Skip candidates should become a sentence the user can confirm, and confounds (intro, shuffle, time of day, undos, few listens, one session) should be rejected before they influence selection.

## How to verify

uv run pytest -o addopts='' -m 'not scale': 283 passed, 1 skipped, 1 deselected. tests/insights: 35 passed. 5-seed confound season: precision 0.936, recall 0.975, 141 LLM calls per season, busiest night 23, warm-cache replay 0 calls.

## Next / handoff

Decisions 0020/0021 and opus-cc tasks T-028, T-029.

---
ts: 2026-10-29T05:24:32Z
agent: cursor-2
branch: cursor/insight-agents-442b
type: decision
tasks: [T-027, T-028, T-029]
files: [docs/decisions/0020-insight-agent-interfaces.md, docs/decisions/0021-insight-agent-defaults.md]
---

## What changed

Decision 0020 records the LLMClient, TrackFeatures and run_nightly signatures the core must provide. Decision 0021 records every default: confound rules, daily cap, not-sure delay, threshold floors and ceilings, the update rule, and the measured call budget.

## Why

The brief requires a decision record for every default and the exact Protocol signatures assumed for opus-cc. Numbered 0020/0021 so they do not collide with decisions 0018/0019 on the unmerged recipe-planner branch.

## How to verify

Docs only; signatures match src/remixer/insights/llm.py, evidence.py and pipeline.py.

## Next / handoff

Handoff.

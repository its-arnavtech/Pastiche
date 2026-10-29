---
ts: 2026-10-29T04:04:10Z
agent: cursor-opus
branch: feature/recipe-planner
type: feat
tasks: [T-022]
files: [src/remixer/planner/plan.py, tests/planner/test_ban.py, tests/planner/test_sampling.py]
---

## What changed

Planner.ban(exclusion, store, lineage): resolves song, stem-type (partial) or sound-level (embedding ball) bans to stems, flags affected current recipes through the lineage index, replaces only banned placements in only the sections containing them, ranks replacements deterministically by similarity^4 x compatibility fit x selection weight under the role, compatibility, cap, window and confirmed-insight rules, marks a section needs_regeneration when nothing is acceptable, and supersedes the old version (never mutated). Patch lists rerender and needs_regeneration sections and exports a renderer request. Rest is fatigue-only and is rejected as a ban.

## Why

T-022 brief section 3; POC 1 spec section 4 retroactive cleanup and acceptance 'banning a song re-renders only the affected sections'.

## How to verify

uv run pytest tests/planner (48 passed). Properties: lineage flags exactly the recipes containing the ban; untouched sections keep their hash; kept placements stay; banned items never in patched or new recipes; cap and role rules hold after patching; stored versions unchanged; patches replay byte-identically. Replacement equals an independent brute-force search on 30-120 song libraries (30 cases); a mutation that inverts the ranking fails that test.

## Next / handoff

Scale run, recipe-store/lineage contracts, decisions, opus-cc/gpt-sol tasks.

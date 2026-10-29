---
ts: 2026-10-29T04:18:31Z
agent: cursor-opus
branch: feature/recipe-planner
type: handoff
tasks: [T-022, T-023, T-024, T-025, T-026]
files: [src/remixer/planner/, tests/planner/, tests/contracts/test_recipe_store.py, tests/contracts/conftest.py, docs/decisions/0018-planner-core-interfaces.md, docs/decisions/0019-planner-defaults.md, pyproject.toml, uv.lock]
---

## What changed

Recipe planner and ban-and-replace (src/remixer/planner/) complete against in-memory fakes. For opus-cc: wire Catalog-backed StemCatalog + NeighborQuery (T-023), RecipeStore + Lineage (T-024; register the adapter in RECIPE_BACKENDS in tests/contracts/conftest.py so test_recipe_store.py runs against it) and tenant/track deletion through Lineage.containing(song=...) (T-025). Exact signatures in docs/decisions/0018. For gpt-sol: the renderer must accept Patch.render_request() (sections with stems in StemPick field names, keyed by section_hash; needs_regeneration indices) and re-render only those sections (T-026). Dependencies: optional group 'planner' = numpy>=2.4.6 (added with uv add --optional planner); tests also use the existing hypothesis/pytest dev deps. Branch feature/recipe-planner is rebased onto dev (PR #1 merged); the planner reuses T-015 fatigue.selection.

## Why

Brief: core-facing needs stay as Protocols in the planner module with fakes; opus-cc owns the core, gpt-sol owns the renderer. Coordination note: after PR #1 merged, dev holds T-020 (gpt-audit), T-021 (adapter contract suite) and decisions up to 0017, so this branch was rebased onto dev and renumbered to T-022..T-026 and decisions 0018/0019.

## How to verify

uv run pytest -o addopts='' -m 'not scale': 282 passed, 2 deselected. Scale (-m scale tests/planner/test_planner_scale.py): passed. 10k recipes / 50k stems: plan 45.8 s, ban of most-used song patched 65 recipes in 0.54 s, peak RSS 309 MB.

## Next / handoff

opus-cc: T-023, T-024, T-025. gpt-sol/opus-cc: T-026.

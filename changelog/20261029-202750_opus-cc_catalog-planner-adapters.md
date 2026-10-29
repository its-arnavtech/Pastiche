---
ts: 2026-10-29T20:27:50Z
agent: opus-cc
branch: dev
type: feat
tasks: [T-023, T-024, T-025]
files: [src/remixer/adapters/planner_catalog.py, src/remixer/adapters/hnsw_index.py, tests/contracts/conftest.py, tests/contracts/test_planner_catalog.py, docs/decisions/0027-catalog-planner-adapters.md]
---

## What changed

Catalog-backed StemCatalog/NeighborQuery (exact stem scan over vectors read back from HNSW), SQLite RecipeStore and Lineage (recipe_versions, recipe_lineage, recipe_refs), delete_track and delete_tenant with blob keys returned.

## Why

The planner (decision 0018) ran only on in-memory fakes; it now plans, bans and deletes against the real catalog.

## How to verify

tests/contracts/test_recipe_store.py 18 passed (in-memory + catalog backends); tests/contracts/test_planner_catalog.py 7 passed.

## Next / handoff

Wire analysis results into the catalog via analysis_row in the analysis pipeline.

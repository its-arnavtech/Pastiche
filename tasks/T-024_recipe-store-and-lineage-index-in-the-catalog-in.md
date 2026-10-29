---
id: T-024
title: Recipe store and lineage index in the Catalog (insert, get by hash, supersede)
status: todo
owner: opus-cc
branch: feature/recipe-store
lane: none
depends_on: [T-022]
owns_paths: [src/remixer/adapters/, src/remixer/interfaces.py]
claimed_at:
heartbeat_at:
priority: P1
---

## Goal

Implement the RecipeStore and Lineage Protocols (src/remixer/planner/store.py, lineage.py; signatures in docs/decisions/0018) in the Catalog. RecipeStore: put(recipe) -> recipe_id (version 1 only, idempotent, stores Recipe.canonical_bytes under its sha256 recipe_id); get(recipe_id) -> Recipe (KeyError if unknown, byte-identical round trip via Recipe.from_bytes); supersede(old_id, new) -> new id (require new.supersedes == old_id == current head of the root, new.version == old.version + 1, same root; raise RecipeStoreError otherwise; versions immutable); head(root_id); versions(root_id) oldest first; heads(batch_id=None). Lineage: add(recipe) idempotent; containing(*, song=None, stem=None, window=None, heads_only=False) -> frozenset[recipe_id] (exactly one key; window ids '<song_id>#<5s index>'); head(root_id) -> id | None; is_head(recipe_id). Suggested tables: recipes(recipe_id, root_id, version, supersedes, batch_id, bytes) and recipe_stems/recipe_windows indexed by song, stem and window. Tenant-scoped.

## Definition of done

Register the adapter in RECIPE_BACKENDS in tests/contracts/conftest.py; all tests/contracts/test_recipe_store.py contracts pass for it, including tenant isolation.

## Progress and handoff log

- 2026-10-29T04:13:23Z cursor-opus: created

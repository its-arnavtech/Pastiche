---
ts: 2026-10-29T04:12:53Z
agent: cursor-opus
branch: feature/recipe-planner
type: decision
tasks: [T-022]
files: [docs/decisions/0018-planner-core-interfaces.md, docs/decisions/0019-planner-defaults.md]
---

## What changed

Decision records for the recipe planner: exact core Protocol signatures (StemCatalog, NeighborQuery, RecipeStore, Lineage, deletion, render_request) and every planner default (compatibility thresholds, Gumbel top-k sampling, diversity, per-song cap, replacement ranking).

## Why

The brief requires decision records for thresholds, sampling and replacement ranking and recorded Protocol signatures for opus-cc. Numbered 0018/0019 because dev uses decisions up to 0017 after PR #1 merged (renumbered on rebase).

## How to verify

Docs only; signatures match src/remixer/planner/{catalog,store,lineage,plan}.py.

## Next / handoff

Open interface tasks T-023..T-026 for opus-cc.

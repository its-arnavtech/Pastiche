---
ts: 2026-10-29T04:12:53Z
agent: cursor-opus
branch: feature/recipe-planner
type: decision
tasks: [T-021]
files: [docs/decisions/0013-planner-core-interfaces.md, docs/decisions/0014-planner-defaults.md]
---

## What changed

Decision records for the recipe planner: exact core Protocol signatures (StemCatalog, NeighborQuery, RecipeStore, Lineage, deletion, render_request) and every planner default (compatibility thresholds, Gumbel top-k sampling, diversity, per-song cap, replacement ranking).

## Why

The brief requires decision records for thresholds, sampling and replacement ranking and recorded Protocol signatures for opus-cc. Numbered 0013/0014 because dev already uses 0010-0012.

## How to verify

Docs only; signatures match src/remixer/planner/{catalog,store,lineage,plan}.py.

## Next / handoff

Open interface tasks T-022..T-025 for opus-cc.

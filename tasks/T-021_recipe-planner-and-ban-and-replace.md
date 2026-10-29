---
id: T-021
title: Recipe planner and ban-and-replace
status: in_progress
owner: cursor-opus
branch: feature/recipe-planner
lane: none
depends_on: [T-015, T-020]
owns_paths: [src/remixer/planner/, tests/planner/]
claimed_at: 2026-10-29T03:52:51Z
heartbeat_at: 2026-10-29T03:52:51Z
priority: P1
---

## Goal

Sectioned, content-addressed recipes with provenance and a lineage index; seeded compatibility-aware stem selection reusing the T-015 selection weight (5% per-song cap, role constraints, diversity, no source-window reuse, confirmed insights only); ban-and-replace for hard, partial and sound-level bans that patches only affected sections into a superseding recipe version or marks them needs_regeneration; synthetic library, property tests, 10k-recipe / 50k-stem scale run, recipe-store and lineage contract tests.

## Definition of done

All planner property tests and contracts pass; scale numbers in the changelog; decisions for thresholds, sampling and replacement ranking; interface tasks opened for opus-cc; PR into dev.

## Progress and handoff log

- 2026-10-29T03:52:51Z cursor-opus: created
- 2026-10-29T03:52:51Z cursor-opus: claimed

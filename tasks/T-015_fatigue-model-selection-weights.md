---
id: T-015
title: Fatigue model + selection weights
status: in_progress
owner: cursor-opus
branch: feature/skip-analytics
lane: none
depends_on: [T-014]
owns_paths: [src/remixer/fatigue/, tests/fatigue/]
claimed_at: 2026-10-29T03:10:35Z
heartbeat_at: 2026-10-29T03:10:35Z
priority: P1
---

## Goal

Exponentially decaying fatigue, selection weight taste x (1 - fatigue) x novelty with a per-source cap (~5%).

## Definition of done

Unit tests for decay, cap and weight composition.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner cursor-opus)
- 2026-10-29T03:10:35Z cursor-opus: claimed

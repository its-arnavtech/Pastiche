---
id: T-015
title: Fatigue model + selection weights
status: todo
owner: cursor-opus
branch: feature/skip-analytics
lane: none
depends_on: [T-014]
owns_paths: [src/remixer/analytics/fatigue.py, src/remixer/analytics/selection.py]
claimed_at:
heartbeat_at:
priority: P1
---

## Goal

Exponentially decaying fatigue, selection weight taste x (1 - fatigue) x novelty with a per-source cap (~5%).

## Definition of done

Unit tests for decay, cap and weight composition.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner cursor-opus)

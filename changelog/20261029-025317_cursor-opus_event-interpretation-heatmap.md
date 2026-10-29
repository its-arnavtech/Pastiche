---
ts: 2026-10-29T02:53:17Z
agent: cursor-opus
branch: feature/skip-analytics
type: feat
tasks: [T-014]
files: [src/remixer/analytics/__init__.py, src/remixer/analytics/events.py, src/remixer/analytics/intervals.py, src/remixer/analytics/interpret.py, src/remixer/analytics/heatmap.py, tests/analytics/, tasks/T-014_event-interpretation-heatmap-detector-simulator.md, tasks/T-015_fatigue-model-selection-weights.md, tasks/T-016_player-ui-with-event-logging.md]
---

## What changed

remixer.analytics: append-only event envelope with validation (events.py); listen reconstruction and interpretation rules as pure functions with every threshold in InterpretConfig (interpret.py: skip bursts within 2 s = one skip of N x 5 s, undo within 6 s cancels the latest press, late return into skipped audio cancels it, replay over heard audio, early/mid/near-end next, previous vs restart); 5 s window heatmap keyed by track_version with reached-window denominator and DetectorConfig (min 3 listens, >= 2 skips, skip rate >= 0.6, undo rate <= 0.2) (heatmap.py). owns_paths of T-014..T-016 updated per decision 0006.

## Why

T-014: spec section 5 interpretation and heatmap, tested before the UI.

## How to verify

uv run pytest tests/analytics

## Next / handoff

Simulator with planted patterns, property tests, multi-million-event scale run.

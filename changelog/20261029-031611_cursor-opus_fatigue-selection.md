---
ts: 2026-10-29T03:16:11Z
agent: cursor-opus
branch: feature/skip-analytics
type: feat
tasks: [T-015]
files: [src/remixer/fatigue/, tests/fatigue/, docs/decisions/0008-fatigue-and-selection-defaults.md]
---

## What changed

remixer.fatigue: credit.py (loudness-share credit assignment over audible stems, track or window level); attribution.py (Bayesian ridge over stem presence or credit share with posterior std, culprits by z-score; numpy); state.py (FatigueModel: exponential decay with configurable half-life, saturating increments, tired = temporary, thumbs-down = permanent flag on direct targets and credited negative evidence on stems of generated tracks, thumbs-up relief, passive early/mid next and exposure fatigue, one-hop embedding-neighbor propagation through a NeighborLookup callable; replay() rebuilds state from the append-only T-014 events + signals with a RecipeLookup callable); selection.py (taste x (1 - fatigue) x novelty_bonus, disliked -> 0, confirmed insights block overlapping ranges, per-source cap max(1, floor(5% x batch)), seeded weighted sampling without replacement); insights.py (confirmed=False by default; yes confirms, no dismisses, unsure stays pending; built from T-014 candidates; answers applied from insight_* events). Decision 0008 records the defaults.

## Why

T-015 brief and spec section 4.

## How to verify

uv run pytest tests/fatigue (or without the torch stack: uv run --no-project --with pytest --with hypothesis --with numpy --with duckdb --with pyarrow pytest tests/fatigue). Attribution: 10/10 seeds isolate the planted culprit among 40 stems from 300 ratings at z >= 3, 5/5 seeds find both of two culprits from 500, no false culprit without one.

## Next / handoff

opus-cc/gpt-sol: the assembler can call select_batch with StemCandidate(stem_id, source_id, taste_score, start_ms, end_ms) and a FatigueModel from replay(events, recipes=lambda track_id, version: [StemUse...], signals=interpret(events).signals, neighbors=lambda stem_id, k: [(id, similarity)]). The neighbor callable should wrap the core VectorIndex; the RecipeLookup should read recipe_stems from the catalog.

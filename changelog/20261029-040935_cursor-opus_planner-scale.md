---
ts: 2026-10-29T04:09:35Z
agent: cursor-opus
branch: feature/recipe-planner
type: bench
tasks: [T-022]
files: [src/remixer/planner/scale.py, tests/planner/test_scale.py]
---

## What changed

Scale run (4-core cloud VM, Python 3.11, numpy): 49,974 synthetic stems (13,158 songs), 10,000 recipes in 100 batches of 100 (4 sections x 4 roles = 160,000 stem slots). Library build 0.79 s; planner init (columnar index + selection weights) 0.21 s; planning 45.82 s (218 recipes/s), slot fill rate 1.0, 13,115 songs used. Ban of the most-used song (song-06147, 79 stem uses): 65 recipes patched in 0.542 s, 69 sections to re-render, 0 needs_regeneration, 191 sections in those recipes provably unchanged, 0 leaks. Memory: peak RSS 308.8 MB (91 MB after the library, 308 MB after storing 10k recipes as canonical bytes plus the lineage index). Optimisation: top-k partition before the exact lexsort and lazy downbeat positions cut planning from 78.4 s to 45.8 s with byte-identical output (same sha256 over 200 recipes before and after). On a 5k-stem library the most-used song tends to be the only fit for a niche tempo/key, so its ban yields needs_regeneration sections (14 of 39) instead of forced matches, as intended.

## Why

T-022 brief section 5.

## How to verify

uv run python -m remixer.planner.scale --stems 50000 --recipes 10000 (prints the JSON above); uv run pytest -m scale tests/planner/test_scale.py (47 s).

## Next / handoff

Recipe-store and lineage contracts, decision records, interface tasks.

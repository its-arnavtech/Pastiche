---
ts: 2026-10-29T03:35:32Z
agent: cursor-opus
branch: feature/skip-analytics
type: handoff
tasks: [T-014, T-015, T-016, T-021]
files: [src/remixer/analytics/, src/remixer/fatigue/, web/, tests/analytics/, tests/fatigue/, tests/web/, tests/contracts/]
---

## What changed

cursor-opus scope complete on feature/skip-analytics (PR into dev). T-014 event schema, interpretation, 5 s heatmap, detector, simulator, property and scale tests. T-015 credit, attribution, fatigue, propagation, selection, insights. T-016 static player, inbox, mock backend, Playwright tests. T-020 adapter contract suite. Detector: 20 seeds precision 1.0000 recall 1.0000 (tp 1086, fp 0, fn 0); sparse 0.981/0.991. Scale from Parquet on a 4-core VM: 1M events 3.93 s, 5M 15.64 s, 10M 30.37 s (329k events/s), P/R 1.0 at every size. Dependencies (optional groups, decision 0006): analytics = duckdb, numpy, pyarrow; web-test = playwright; hypothesis in dev.

## Why

Final handoff for the brief.

## How to verify

uv run pytest: 224 passed, 1 deselected (uv run pytest -m scale for the 2M run). Web tests need uv run playwright install chromium once. Plain CI without torch: uv run --no-project --with pytest --with hypothesis --with numpy --with duckdb --with pyarrow pytest tests/analytics tests/fatigue (110 passed).

## Next / handoff

opus-cc: merge feature/skip-analytics into dev; regenerate CHANGELOG.md there (it is not regenerated on this branch). Wire the real FastAPI backend to the routes in decision 0009; give replay() a RecipeLookup over recipe_stems and a NeighborLookup over the VectorIndex (T-015 changelog); register the commercial profile in tests/contracts/conftest.py. Not done: tenant-deletion contract (no interface yet), LLMClient contract (needs Ollama). Nothing added to docs/NEEDS_USER.md.

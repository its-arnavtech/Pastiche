---
ts: 2026-10-29T20:37:14Z
agent: opus-cc
branch: dev
type: feat
tasks: [T-028, T-029]
files: [src/remixer/adapters/ollama_llm.py, src/remixer/adapters/insight_job.py, src/remixer/adapters/planner_catalog.py, src/remixer/cli.py, profile.yaml, tests/contracts/test_insight_job.py, docs/decisions/0028-ollama-client-and-nightly-job.md, docs/NEEDS_USER.md]
---

## What changed

OllamaClient: response_format -> format json, think=false with thinking fallback, available() checks the model is pulled. Nightly job remixer insights nightly: loads/stores InsightState under <data>/insights, playback events, CatalogTrackFeatures from recipes or analysis, skips when the model is down. Profile uses the already-pulled qwen3:4b.

## Why

T-028/T-029: the insight layer had only a mock model and no job.

## How to verify

tests/contracts/test_insight_job.py 8 passed against a scripted Ollama HTTP server; live run on qwen3:4b over 6 fixture nights: JSON parses, narrator valid, analyst/skeptic window ids garbled about half the time and rejected, precision 1.0.

## Next / handoff

User: optional Task Scheduler entry (NEEDS_USER item 5). cursor-2: consider echoing short indices instead of window ids for small models.

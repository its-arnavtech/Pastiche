---
ts: 2026-10-29T05:24:32Z
agent: cursor-2
branch: cursor/insight-agents-442b
type: handoff
tasks: [T-027, T-028, T-029]
files: [src/remixer/insights/, docs/decisions/0020-insight-agent-interfaces.md, docs/decisions/0021-insight-agent-defaults.md]
---

## What changed

Insight layer is done against MockLLM. For opus-cc: T-028 is an Ollama LLMClient with complete(prompt, system=None, **kw) and available(); T-029 is the nightly job that persists InsightState and supplies TrackFeatures.window_features from the catalog. Both signatures are in docs/decisions/0020. The inbox already reads inbox_view through the mock backend. No torch and no new packages.

## Why

The layer must not import or edit the core. A real model and the scheduler belong to opus-cc.

## How to verify

Same suite as the feat entry. Surfaced insights over 5 synthetic seasons: precision 0.936, recall 0.975. Daily budget 30; observed max 23 calls in a night; a warm cache serves the season with 0 calls.

## Next / handoff

opus-cc: T-028 then T-029.

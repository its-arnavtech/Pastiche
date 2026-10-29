---
id: T-028
title: Ollama-backed LLMClient for the insight layer
status: done
owner: opus-cc
branch:
lane: none
depends_on: [T-027]
owns_paths: [src/remixer/adapters/, src/remixer/interfaces.py]
claimed_at:
heartbeat_at: 2026-10-29T20:37:02Z
priority: P1
---

## Goal

Implement remixer.insights.llm.LLMClient against a local Ollama server (do not edit src/remixer/insights/). complete(prompt, system=None, **kw) -> str, available() -> bool. The prompt carries one JSON request after the line REQUEST:; kw is temperature=0 and response_format=json. Return one JSON object. available() is false when Ollama is not running, and the nightly job then skips. Signatures and schemas are in docs/decisions/0020. No torch.

## Definition of done

A contract test: scripted Ollama responses round-trip through analyst/skeptic/narrator; available() is false when the server is down; the insight pipeline still falls back if the reply is malformed.

## Progress and handoff log

- 2026-10-29T05:22:57Z cursor-2: created
- 2026-10-29T20:37:02Z opus-cc: done: OllamaClient (format/think/available fixes) + remixer.adapters.insight_job; contract tests tests/contracts/test_insight_job.py; live smoke against qwen3:4b (decision 0028).

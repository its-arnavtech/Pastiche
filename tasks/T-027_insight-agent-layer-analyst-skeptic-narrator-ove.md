---
id: T-027
title: Insight agent layer: analyst, skeptic, narrator over skip candidates
status: in_progress
owner: cursor-2
branch: cursor/insight-agents-442b
lane: none
depends_on: [T-014, T-015, T-016]
owns_paths: [src/remixer/insights/, tests/insights/]
claimed_at: 2026-10-29T05:17:48Z
heartbeat_at: 2026-10-29T05:17:48Z
priority: P1
---

## Goal

Turn T-014 candidate skip windows into plain-language insights with an LLM, never interrupting playback: LLMClient Protocol + deterministic MockLLM; Analyst, Skeptic and Narrator roles as pure functions with JSON outputs validated against schemas (malformed output falls back, never crashes); insight lifecycle (proposed, shown, confirmed, dismissed, not_sure) with passive inbox delivery, about one new insight per day, 3-listen rule, suppression after dismissal, not-sure delay; bounded per-user threshold tuning from answers; cost control (detector pre-filter, response cache, per-track batching, daily call budget); simulator tests with planted dislikes and confounds reporting precision and recall; wired into the player's insights inbox via the mock backend; interface tasks for opus-cc (Ollama LLMClient adapter, nightly job).

## Definition of done

All tests pass; decision records for thresholds, caps, budget and update rule; precision/recall and call-budget numbers in the changelog; opus-cc tasks opened with Protocol signatures; PR into dev.

## Progress and handoff log

- 2026-10-29T04:40:17Z cursor-opus: created
- 2026-10-29T04:40:17Z cursor-opus: claimed
- 2026-10-29T05:17:48Z cursor-2: takeover from cursor-opus: cursor-opus stopped at a usage limit with the insight layer uncommitted: roles, pipeline and inbox wiring exist, tests and decision records do not.

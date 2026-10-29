---
id: T-029
title: Nightly insight job: run the pipeline and persist state
status: todo
owner: opus-cc
branch:
lane: none
depends_on: [T-027, T-028]
owns_paths: [src/remixer/adapters/]
claimed_at:
heartbeat_at:
priority: P1
---

## Goal

Schedule run_nightly (remixer.insights.pipeline) once per user per local night. Load InsightState.from_json, pass playback events with wall_time <= now_ms, an Ollama LLMClient (T-028), and a TrackFeatures adapter whose window_features(track_id, track_version) returns 5-second WindowFeatures (loudness_lufs, tempo_bpm, section, stems) from the catalog analysis. Persist state.to_json(). Do not touch playback. The inbox reads inbox_view(state). Exact signatures in docs/decisions/0020.

## Definition of done

A fixture night produces the same InsightState as calling run_nightly directly; a second run the same night makes no new LLM calls when the cache is warm; a down model skips the night without losing state.

## Progress and handoff log

- 2026-10-29T05:22:57Z cursor-2: created

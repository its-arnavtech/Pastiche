---
id: T-030
title: Re-embed FP32 CLAP and retrain finite taste checkpoint
status: todo
owner: opus-cc
branch: dev
lane: gpu
depends_on: [T-005, T-017]
owns_paths: [src/remixer/gpu/, data/embeddings/, data/models/taste/]
claimed_at:
heartbeat_at:
priority: P1
---

## Goal

Recover from the all-NaN old CLAP embeddings and taste checkpoint. FP16 log-floor repair, version isolation, finite guards and current-version rating recovery are implemented and tested in the shared tree. Restart the old embedding process under logmel-f32-v2, then retrain; retain old artifacts for diagnosis.

## Definition of done

New-version embedding checkpoints and trained arrays are finite; trained metadata matches current CLAP version; validate new checkpoint through trained OpenVINO and synth fitness adapters. Do not certify old corrupt weights. See changelog/20261029-053514_gpt-sol_reject-nan-taste-and-fp16-logmel.md and docs/reports/cpu-lane.md.

## Progress and handoff log

- 2026-10-29T14:13:28Z gpt-sol: created
- 2026-10-29T14:20:52Z opus-cc: renumbered from T-022 at the PR #2/#3 merge (PR #2 already uses T-022..T-026); see decision 0023.

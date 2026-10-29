---
id: T-030
title: Re-embed FP32 CLAP and retrain finite taste checkpoint
status: done
owner: opus-cc
branch: dev
lane: gpu
depends_on: [T-005, T-017]
owns_paths: [src/remixer/gpu/, data/embeddings/, data/models/taste/]
claimed_at: 2026-10-29T14:35:13Z
heartbeat_at: 2026-10-29T14:35:13Z
priority: P1
---

## Goal

Recover from the all-NaN old CLAP embeddings and taste checkpoint. FP16 log-floor repair, version isolation, finite guards and current-version rating recovery are implemented and tested in the shared tree. Restart the old embedding process under logmel-f32-v2, then retrain; retain old artifacts for diagnosis.

## Definition of done

New-version embedding checkpoints and trained arrays are finite; trained metadata matches current CLAP version; validate new checkpoint through trained OpenVINO and synth fitness adapters. Do not certify old corrupt weights. See changelog/20261029-053514_gpt-sol_reject-nan-taste-and-fp16-logmel.md and docs/reports/cpu-lane.md.

## Progress and handoff log

- 2026-10-29T14:13:28Z gpt-sol: created
- 2026-10-29T14:20:52Z opus-cc: renumbered from T-022 at the PR #2/#3 merge (PR #2 already uses T-022..T-026); see decision 0023.
- 2026-10-29T14:35:13Z opus-cc: claimed
- 2026-10-29T14:35:13Z opus-cc: done: Verified fix on dev (d05da63, version laion/clap-htsat-unfused@transformers-5.21.0-logmel-f32-v2). Re-embedded all 2000 stems / 86,816 windows on the RTX 4060 (135 windows/s, batch 16): every vector finite. Old corrupt embeddings kept at data/embeddings/laion_clap-htsat-unfused_transformers-5.21.0 (50/50 sampled files nonfinite). The old NaN taste checkpoint was overwritten by the retrain (same filename); taste.train now sets aside checkpoints from another embedding version as *.superseded-<version>.pt. Retrained: val AUC 0.939 (>0.85), planted-direction correlation 0.996, all weights finite (.pt and .npz). Mixing refusal: tests/test_taste.py::test_synthetic_and_real_never_mix passes. Handoff: loads through npu.trained.TasteWeights and synth.taste.ClapTasteScorer (identity clap-taste-v1:...-logmel-f32-v2:e5d214b7, finite scores); OpenVINO trained export runs NPU 122k / iGPU 493k inferences/s, max reference error 7e-4.

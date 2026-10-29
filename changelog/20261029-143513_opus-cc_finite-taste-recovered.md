---
ts: 2026-10-29T14:35:13Z
agent: opus-cc
branch: dev
type: fix
tasks: [T-030, T-017, T-005]
files: [src/remixer/gpu/taste.py, tests/test_taste.py]
---

## What changed

Verified fix on dev (d05da63, version laion/clap-htsat-unfused@transformers-5.21.0-logmel-f32-v2). Re-embedded all 2000 stems / 86,816 windows on the RTX 4060 (135 windows/s, batch 16): every vector finite. Old corrupt embeddings kept at data/embeddings/laion_clap-htsat-unfused_transformers-5.21.0 (50/50 sampled files nonfinite). The old NaN taste checkpoint was overwritten by the retrain (same filename); taste.train now sets aside checkpoints from another embedding version as *.superseded-<version>.pt. Retrained: val AUC 0.939 (>0.85), planted-direction correlation 0.996, all weights finite (.pt and .npz). Mixing refusal: tests/test_taste.py::test_synthetic_and_real_never_mix passes. Handoff: loads through npu.trained.TasteWeights and synth.taste.ClapTasteScorer (identity clap-taste-v1:...-logmel-f32-v2:e5d214b7, finite scores); OpenVINO trained export runs NPU 122k / iGPU 493k inferences/s, max reference error 7e-4.

## Why

gpt-sol found the fp16 log-mel front end produced NaN CLAP embeddings and a NaN taste checkpoint.

## How to verify

uv run pytest tests/test_taste.py tests/test_embed.py tests/npu tests/cpu/test_synth.py

## Next / handoff

gpt-sol: synth --fitness auto now picks the finite trained checkpoint.

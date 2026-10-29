---
ts: 2026-10-29T04:30:42Z
agent: opus-cc
branch: dev
type: feat
tasks: [T-017]
files: [src/remixer/gpu/taste.py, src/remixer/gpu/cli.py, tests/test_taste.py]
---

## What changed

remixer taste: GPU MLP (512->256->64->1 by default, same shape as the NPU scorer; --width scales it for load) trained on CLAP window embeddings. Until real ratings exist it plants a hidden taste direction and samples thumbs up/down for 30% of windows into the synthetic_ratings event stream (every row synthetic=true); load_ratings('synthetic'|'real') returns exactly one kind and asserts no mixing; real ratings come only from rating_events with synthetic=0. Saves .pt and .npz weights to data/models/taste/, logs samples/s, val AUC, and correlation with the planted direction.

## Why

T-017.

## How to verify

uv run pytest tests/test_taste.py; uv run remixer taste --epochs 50

## Next / handoff

gpt-sol: data/models/taste/taste-mlp-v1-synthetic-w256.npz holds weights named 0.weight, 0.bias, 3.weight, 3.bias, 5.weight, 5.bias (GELU between layers) if you want the NPU lane to score with a trained model instead of the random one.

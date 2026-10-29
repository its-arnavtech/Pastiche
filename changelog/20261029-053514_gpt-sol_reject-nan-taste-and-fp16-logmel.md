---
ts: 2026-10-29T05:35:14Z
agent: gpt-sol
branch: dev
type: fix
tasks: [T-005, T-017, T-011, T-012]
files: [src/remixer/gpu/embed.py, src/remixer/gpu/taste.py, tests/test_embed.py, tests/test_taste.py, src/remixer/npu/trained.py, src/remixer/npu/scorer.py, src/remixer/npu/cli.py, src/remixer/synth/taste.py, src/remixer/synth/lab.py, src/remixer/synth/cli.py, tests/npu/test_trained.py, tests/cpu/test_synth.py]
---

## What changed

Trained handoff validation found all weights nonfinite and all values in three sampled CLAP checkpoint files nonfinite. Run front-end power/mel/log calculations in FP32 outside autocast: FP16 cannot represent the 1e-10 log floor. Version the embedding cache and index with logmel-f32-v2; reject nonfinite vectors before persistence/training and reject nonfinite loss/weights before model persistence. Current-version synthetic ratings are planted even when older-version history exists; event IDs include the target window identity.

Added trained GELU/bias export and NumPy inference, plus a single-parent CPU CLAP fitness adapter. Workers render candidates; the parent batches their embeddings and scores them. Evolution checkpoints pin scorer identity for reproducible resume. Automatic selection warns and retains the explicit heuristic/random probe if the checkpoint is invalid; explicit trained selection fails.

## Why

The conditional taste handoff arrived but was numerically corrupt. Model shape compatibility alone is insufficient. Reject invalid data rather than propagating NaNs into selection or benchmark claims.

## How to verify

CPU half-autocast quiet-audio regression, trained-model PyTorch/NumPy/OpenVINO parity, invalid-checkpoint rejection, parent-only batching and versioned rating tests. A real corrected CPU CLAP forward produced finite features and a finite 512-dimensional embedding (data/verification/clap-fp32.json). The existing checkpoint's six parameter arrays and three sampled embedding files were entirely nonfinite.

## Next / handoff

URGENT opus-cc: the embedding process loaded the old code. Checkpoint-stop and restart embedding under the new logmel-f32-v2 version, then retrain before using the taste checkpoint. Old files/index are retained. The new version isolates the corrupt cache/index. CPU/NPU locks remain yours; gpt-sol started no GPU jobs. Measured lane performance still uses explicitly labeled heuristic fitness and the seeded random ReLU probe.

---
id: T-017
title: Taste model training loop
status: done
owner: opus-cc
branch: dev
lane: gpu
depends_on: [T-005]
owns_paths: [src/remixer/gpu/taste.py]
claimed_at: 2026-10-29T04:30:46Z
heartbeat_at: 2026-10-29T07:02:01Z
priority: P2
---

## Goal

GPU training loop on embeddings; until real ratings exist it trains on synthetic ratings flagged synthetic=true.

## Definition of done

Train/eval loop runs on GPU; synthetic rows never mix with real taste data.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner opus-cc)
- 2026-10-29T04:30:46Z opus-cc: claimed
- 2026-10-29T04:30:48Z opus-cc: handoff: trainer landed; first GPU run after full-corpus embeddings
- 2026-10-29T07:02:01Z opus-cc: done: Retrained on corrected CLAP vectors (logmel-f32-v2, 2000 stems / 86,816 windows, finite): 25,970 synthetic ratings (flagged synthetic), 200 epochs, val AUC 0.939, val acc 0.866, planted-direction correlation 0.996, 1.53M samples/s. Earlier checkpoint was NaN from the fp16 log-mel bug (gpt-sol fix).

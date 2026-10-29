---
id: T-017
title: Taste model training loop
status: todo
owner: opus-cc
branch: dev
lane: gpu
depends_on: [T-005]
owns_paths: [src/remixer/gpu/taste.py]
claimed_at:
heartbeat_at:
priority: P2
---

## Goal

GPU training loop on embeddings; until real ratings exist it trains on synthetic ratings flagged synthetic=true.

## Definition of done

Train/eval loop runs on GPU; synthetic rows never mix with real taste data.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner opus-cc)

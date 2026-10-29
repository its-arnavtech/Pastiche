---
id: T-005
title: Embedding worker
status: todo
owner: opus-cc
branch: dev
lane: gpu
depends_on: [T-004]
owns_paths: [src/remixer/gpu/embed.py, src/remixer/adapters/vector_index.py]
claimed_at:
heartbeat_at:
priority: P1
---

## Goal

CLAP or MERT embeddings per stem and per 5-second window, batched to fill VRAM, stored in the vector index.

## Definition of done

Windows/sec logged; embeddings keyed by (content hash, model version); vector index search works.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner opus-cc)

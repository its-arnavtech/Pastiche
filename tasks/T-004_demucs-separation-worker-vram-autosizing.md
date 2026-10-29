---
id: T-004
title: Demucs separation worker, VRAM autosizing
status: todo
owner: opus-cc
branch: dev
lane: gpu
depends_on: [T-002, T-003]
owns_paths: [src/remixer/gpu/separate.py, src/remixer/gpu/vram.py, src/remixer/gpu/prefetch.py]
claimed_at:
heartbeat_at:
priority: P0
---

## Goal

htdemucs fp16 separation with pynvml VRAM probe, OOM halve-and-retry with remembered size, prefetch pipeline on feeder cores into pinned memory 2+ batches ahead, heavy mode (htdemucs_ft + shifts) as pure load generator.

## Definition of done

Separates the synthetic corpus resumably, cached by (content hash, model version); logs audio-sec/wall-sec, GPU util, VRAM.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner opus-cc)

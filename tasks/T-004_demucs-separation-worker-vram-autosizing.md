---
id: T-004
title: Demucs separation worker, VRAM autosizing
status: done
owner: opus-cc
branch: dev
lane: gpu
depends_on: [T-002, T-003]
owns_paths: [src/remixer/gpu/separate.py, src/remixer/gpu/vram.py, src/remixer/gpu/prefetch.py]
claimed_at: 2026-10-29T02:45:55Z
heartbeat_at: 2026-10-29T05:07:30Z
priority: P0
---

## Goal

htdemucs fp16 separation with pynvml VRAM probe, OOM halve-and-retry with remembered size, prefetch pipeline on feeder cores into pinned memory 2+ batches ahead, heavy mode (htdemucs_ft + shifts) as pure load generator.

## Definition of done

Separates the synthetic corpus resumably, cached by (content hash, model version); logs audio-sec/wall-sec, GPU util, VRAM.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner opus-cc)
- 2026-10-29T02:45:56Z opus-cc: claimed
- 2026-10-29T03:28:25Z opus-cc: separation worker landed; T-004 stays open for heavy-mode tuning in the bench
- 2026-10-29T04:27:47Z opus-cc: running full-corpus separation
- 2026-10-29T05:07:30Z opus-cc: done: 500/500 tracks separated (htdemucs fp16, batch 10, 54x realtime incl. stem writes under concurrent CPU-lane load)

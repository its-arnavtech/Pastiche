---
id: T-019
title: Stretch: music-generation model inference loop for extra GPU load
status: done
owner: opus-cc
branch: dev
lane: gpu
depends_on: [T-004]
owns_paths: [src/remixer/gpu/musicgen.py, docs/licenses.md]
claimed_at: 2026-10-29T04:33:05Z
heartbeat_at: 2026-10-29T06:53:56Z
priority: P3
---

## Goal

Small music-generation model inference loop to use GPU headroom; license recorded in docs/licenses.md.

## Definition of done

Runs inside the GPU lane; license documented.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner opus-cc)
- 2026-10-29T04:33:05Z opus-cc: claimed
- 2026-10-29T06:53:56Z opus-cc: done: MusicGen-small fp16 loop verified on the RTX 4060: batch 8 x 256 tokens, 160 clips / 809.6 audio-s generated in 156 s = 5.19 audio-s/s (262.6 tokens/s), VRAM peak 1.74 GiB; outputs discarded; CC-BY-NC-4.0 weights local only (docs/licenses.md).

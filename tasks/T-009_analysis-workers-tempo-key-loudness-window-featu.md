---
id: T-009
title: Analysis workers (tempo, key, loudness, window features)
status: done
owner: gpt-sol
branch: dev
lane: cpu
depends_on: [T-002]
owns_paths: [src/remixer/cpu/analyze.py]
claimed_at: 2026-10-29T02:37:23Z
heartbeat_at: 2026-10-29T04:16:39Z
priority: P1
---

## Goal

Per track and per stem: tempo and beat grid, key, LUFS, energy curve, 5-second window features, in a process pool sized from config/resources.yaml.

## Definition of done

Correct on synthetic ground truth; resumable via job queue; logs items/sec.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner gpt-sol)
- 2026-10-29T02:37:23Z gpt-sol: claimed
- 2026-10-29T03:04:33Z gpt-sol: Implementations committed fb81ca7; full suite42 passed and17 focused regressions passed. Analysis and NPU sustain active; peak runner will tune then sustain each CPU stage after analysis.
- 2026-10-29T03:20:05Z gpt-sol: All2500 mixes/stems analyzed without errors in1131.44s:26.51tracks/min; baseline MAE5.376BPM andkey51%. Inspecting octave/key confusions before final acceptance.
- 2026-10-29T03:40:28Z gpt-sol: Track refinement completed:100%key accuracy and0.276BPM MAE over500tracks;mix-only limitations retained. Tuning throughfinalsynth stage, then4x600s CPU sustains. IntelGPU600s=84806embeddings/s;CPUbaseline followedbydualasyncIntelrun.
- 2026-10-29T04:16:39Z gpt-sol: done: Analyzed2500 files/500 tracks without errors;100%stem-supported key accuracy,0.2756BPM MAE;mix-only51%key and0.3338BPM MAE retained. Durablequeue and provenance tests pass. Full76tests plusfocused22passed.

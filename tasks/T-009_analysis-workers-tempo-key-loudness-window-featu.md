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
heartbeat_at: 2026-10-29T14:11:46Z
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
- 2026-10-29T05:12:45Z gpt-sol: handoff: Finaltrackestimatesuseharmonic-keyanddrum/mix/basspulseagreement;original500key100%,BPMMAE0.275584;varied24key91.67%,BPMMAE0.285074. Mix-onlylimitationsretained. Freshqueuepathwritestracksummaryandstrictsource/windowprovenance.
- 2026-10-29T14:11:46Z gpt-sol: done: Final stem-supported track estimates: original 500 tracks key 100%, BPM MAE 0.275584; varied 24 tracks key 91.67%, BPM MAE 0.285074. Blind mix baselines retained. All 2620 files analyzed without errors; queue writes track summaries. Full suite 239 passed.

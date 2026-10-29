---
id: T-011
title: Evolutionary synth lab
status: done
owner: gpt-sol
branch: dev
lane: cpu
depends_on: [T-010]
owns_paths: [src/remixer/synth/]
claimed_at: 2026-10-29T02:44:16Z
heartbeat_at: 2026-10-29T14:11:46Z
priority: P2
---

## Goal

Software-generated note sequences rendered by an evolutionary synth; usable as extra CPU load.

## Definition of done

Deterministic by seed; generations/sec logged.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner gpt-sol)
- 2026-10-29T02:44:17Z gpt-sol: claimed
- 2026-10-29T03:04:39Z gpt-sol: Implementations committed fb81ca7; full suite42 passed and17 focused regressions passed. Analysis and NPU sustain active; peak runner will tune then sustain each CPU stage after analysis.
- 2026-10-29T03:40:32Z gpt-sol: Track refinement completed:100%key accuracy and0.276BPM MAE over500tracks;mix-only limitations retained. Tuning throughfinalsynth stage, then4x600s CPU sustains. IntelGPU600s=84806embeddings/s;CPUbaseline followedbydualasyncIntelrun.
- 2026-10-29T04:16:44Z gpt-sol: Fullsuite76andfocused22passed;codecomplete. Four600s sustains inprogress;bothIntelengines heldthroughpeak. Reportandscalingfigureatdocs/reports/cpu-lane.md.
- 2026-10-29T04:47:50Z gpt-sol: done: Deterministicfitnessprotocol,selection,crossover,mutation,atomicgenerationresume implemented.601.19s sustain746generations,2382.47clips/min. Exactresume tested;heuristicsyntheticfitnessuntilT017adapter.
- 2026-10-29T14:11:46Z gpt-sol: done: Added one-parent CPU CLAP trained-fitness adapter, batch scoring, pinned scorer identity and finite validation. Measured 601.19-second sustain remains heuristic: late T017 checkpoint was all NaN. Minimal upstream FP32/version/ratings repair logged; coordinator must restart embeddings and retrain. Actual corrected CPU CLAP forward finite. Full suite 239 passed.

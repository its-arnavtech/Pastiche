---
id: T-012
title: NPU/iGPU OpenVINO lane
status: in_progress
owner: gpt-sol
branch: dev
lane: npu
depends_on: [T-005]
owns_paths: [src/remixer/npu/]
claimed_at: 2026-10-29T02:45:54Z
heartbeat_at: 2026-10-29T04:16:45Z
priority: P1
---

## Goal

Taste scorer and similarity scoring exported to OpenVINO, run on NPU and iGPU in parallel with GPU work; CPU fallback.

## Definition of done

Inferences/sec per device logged; falls back cleanly when export fails.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner gpt-sol)
- 2026-10-29T02:45:54Z gpt-sol: claimed
- 2026-10-29T03:04:41Z gpt-sol: Implementations committed fb81ca7; full suite42 passed and17 focused regressions passed. Analysis and NPU sustain active; peak runner will tune then sustain each CPU stage after analysis.
- 2026-10-29T03:40:34Z gpt-sol: Track refinement completed:100%key accuracy and0.276BPM MAE over500tracks;mix-only limitations retained. Tuning throughfinalsynth stage, then4x600s CPU sustains. IntelGPU600s=84806embeddings/s;CPUbaseline followedbydualasyncIntelrun.
- 2026-10-29T04:16:45Z gpt-sol: Fullsuite76andfocused22passed;codecomplete. Four600s sustains inprogress;bothIntelengines heldthroughpeak. Reportandscalingfigureatdocs/reports/cpu-lane.md.

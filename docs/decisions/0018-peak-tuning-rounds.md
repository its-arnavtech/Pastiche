# 0018 Peak tuning rounds: 15-minute sustains, per-pass GPU unit

- Context: round 1 (ramp + 60-minute sustain, all lanes) finished. Under the full combined sustain the CPU render lane fell from ~12.5 (90 s combined step) to 2.4 rendered audio-s/s and the NPU lane from ~76k to 14k inferences/s, while the GPU held 94 % utilization. The GPU sustain step runs the heavy generator (htdemucs_ft, 2 shifts = 8 model passes per audio second), so its raw audio-s/s was not comparable with the light ramp steps.
- Decision:
  - GPU throughput for heavy steps is reported as model-pass audio-s/s (`model_rate_x`); a light htdemucs step is one pass per audio second, so both share one unit. Round 1's stored steps were re-parsed with this rule.
  - Telemetry records the effective CPU clock (`cpu_mhz_eff` = base MHz x PDH `% Processor Performance`), since psutil only reports the 2.3 GHz base clock. Idle-dGPU NVML power readings above twice the power limit are dropped as invalid.
  - Tuning rounds use 15-minute sustains (thermal steady state is reached after ~5 minutes on this chassis), each changing one variable. The score is the brief's rule: mean over lanes of sustained throughput relative to round 1. Tuning stops when two consecutive rounds change the score by less than 3 %.
- Alternatives: 60-minute sustains for every round (4+ hours per two rounds, while other agents need the machine); a single composite unit across lanes (no meaningful common unit exists).
- Consequences: round 1 remains the 60-minute endurance record; the best tuned configuration is reported with its 15-minute numbers and the difference is stated in docs/PEAK_REPORT.md.

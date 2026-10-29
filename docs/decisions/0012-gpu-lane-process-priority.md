# 0012 GPU-lane processes run at above-normal priority

- Context: with gpt-sol's CPU sustain holding the CPU at 91 %, the isolated GPU ramp collapsed to 8-24 % GPU utilization and 7-31 audio-s/s (reports/peak/20261028-225051): the GPU feeder threads and the CUDA launch thread were starved, so the GPU idled between batches. The same batch-10 run at normal priority under no CPU load did 62-64 audio-s/s.
- Decision: `remixer separate` and `remixer embed` raise their own process to ABOVE_NORMAL priority via the compute adapter (`LocalCompute.prioritize_current_process`). Only our own processes are affected; no system setting changes.
- Alternatives: lower the CPU lane's priority (touches gpt-sol's code); shrink the CPU lane by more cores (wastes CPU).
- Consequences: under the same 91 % CPU load the GPU lane went back to 56 audio-s/s. The GPU lane needs only ~4 cores' worth of feeding, so the CPU lane loses very little.

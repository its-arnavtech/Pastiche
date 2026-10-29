# 0010 GPU batch sizing: calibrate by throughput, not by OOM

- Context: on this Windows laptop (WDDM driver 610.74) the NVIDIA "CUDA sysmem fallback" spills allocations beyond the 8 GB into shared system RAM instead of raising OOM. A Demucs batch of 24 ran for 10+ minutes without error; batch 12 ran at half the speed of batch 10. OOM halve-and-retry alone never fires.
- Decision: `remixer.gpu.vram.BatchSizer.calibrate` first bounds the batch by a linear memory fit (peak at B=1, B=2, measured with cudnn autotune off) against free VRAM minus 0.6 GiB, then times candidate batches and stops at the first >15 % drop in items/s (the spill signature). The chosen size is remembered per (model, precision, segment/window) in `data/state/gpu_sizes.json`; OOM still halves it.
- Alternatives: disable sysmem fallback in the NVIDIA control panel (driver setting: off-limits for agents); size by memory only (over-estimates, spills).
- Consequences: ~30 s calibration on first use per model. htdemucs fp16 lands at batch 10 (about 3.6 GiB of real allocation; the rest is cudnn workspace and allocator slack).

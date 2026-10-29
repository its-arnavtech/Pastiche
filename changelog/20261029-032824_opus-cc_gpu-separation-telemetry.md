---
ts: 2026-10-29T03:28:24Z
agent: opus-cc
branch: dev
type: feat
tasks: [T-004, T-006]
files: [src/remixer/adapters/sqlite_queue.py, src/remixer/interfaces.py, src/remixer/gpu/cli.py, src/remixer/gpu/prefetch.py, src/remixer/gpu/separate.py, src/remixer/gpu/vram.py, src/remixer/ingest.py, src/remixer/telemetry/cli.py, src/remixer/telemetry/dashboard.py, src/remixer/telemetry/sampler.py, src/remixer/telemetry/win_engines.py, tests/test_gpu_lane.py]
---

## What changed

GPU lane: remixer ingest (corpus track.json + read-only library -> catalog + separate jobs); remixer separate: htdemucs fp16, cross-track segment batching, GPU overlap-add, streaming PCM16 stem writer, ack after write, cached by (track hash, model version), --heavy (htdemucs_ft bag + shifts, outputs discarded), --loop, --duration; feeder thread pool decoding into pinned memory >= 2 batches ahead; VRAM batch calibration (memory fit + items/s search, remembered in data/state/gpu_sizes.json, OOM halve). JobQueue.release(). Telemetry: Sampler (pynvml per-field, per-core CPU, RAM, disk MB/s, optional LibreHardwareMonitor CPU temp, Intel iGPU via PDH GPU Engine counters with DXGI LUID mapping) -> Parquet parts; static HTML dashboard.

## Why

T-004 and T-006.

## How to verify

uv run pytest tests/test_gpu_lane.py; uv run remixer separate --duration 60; uv run remixer telemetry run --duration 10 && uv run remixer telemetry dashboard

## Next / handoff

Measured: htdemucs fp16 ~51x realtime sustained at batch 10 (calibrated; batch 12+ spills into shared memory on WDDM - no OOM, 2x slower). GPU sits at 86-89 C, SM clock 1.6-2.3 GHz, 50-75 W of a 90 W enforced limit: thermally bound. NVML utilization query returns Unknown Error when the dGPU idles (gaps in telemetry, harmless). No NPU perf counters exist on this machine: the NPU lane must report its own inferences/s.

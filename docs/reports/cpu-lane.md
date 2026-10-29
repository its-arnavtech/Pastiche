# CPU and Intel lane measurements

Generated 2026-10-29T14:13:55+00:00 from local measured artifacts.

Peak sequence phase: **complete**. Agent: `gpt-sol`, branch `dev`.

## Hardware and method

Intel Core Ultra 9 185H, 22 logical / 16 physical cores, Intel Arc iGPU, Intel AI Boost NPU, 23.4 GiB RAM and NVMe. The NVIDIA lane belongs to opus-cc. The configured CPU budget is 17 workers, or 16 while the Intel lane borrows one host thread. Native math threads are limited to one per worker; multiprocessing uses spawn. The Windows power plan was Balanced at bootstrap; no power, firmware, driver, fan or clock settings were changed by this lane.

Measurements exclude worker warm-up in the tuner. Every timed CPU unit forces actual work; cache hits are not counted as compute. Full-corpus analysis is resumable and its elapsed time covers the completed invocation after the checkpointed algorithm restart. Host CPU, RAM and disk figures include concurrent agents and applications; process-tree RSS is separate. Missing temperature sensors are reported as unavailable. Throughput differences alone do not establish thermal or memory-bandwidth limits.

The first corpus run used the standalone 10 GiB disk floor while the shared guard was landing. Subsequent stages use remixer.guards in unleashed mode and atomic checkpoints. All audio generated here is synthetic; no real taste data is used by the heuristic or random MLP.

## Corpus

500 tracks; 29.94 hours; 639.16 wall seconds; **168.61 audio-seconds / wall-second**. Each has 44.1 kHz stereo PCM16 drums, bass, vocals-like lead, other, and their exact integer-summed mix, with seeded BPM, key and beat positions.

Host CPU mean 89.85%, peak 91.46%; process-tree RSS peak 1.21 GiB. Host write throughput 152.47 MB/s. Disk-floor stop: None; real library files registered: 0.

The original baseline uses procedural-v1. The current default generator also varies eight chord progressions, four kick/snare styles, note rests and hat velocities under procedural-v2. Legacy seed identities and bytes remain reproducible with --legacy-arrangement. Additional procedural-v2 validation tracks completed: 24; their track key accuracy: 91.67%; BPM MAE: 0.285.

## Analysis accuracy

Analyzed 2500 mixes/stems (500 tracks). Mean absolute BPM error: **0.276 BPM**. Exact tonic-and-mode accuracy: **100.00%**. Throughput 26.51 tracks/minute or 132.57 mixes/stems per minute; errors: 0.

Method: key from harmonic other stem; drum/mix/bass tempo agreement with octave resolution; no truth labels used during inference. Mix-only key accuracy remains 51.00%; mix-only BPM MAE 0.334. Post-analysis refinement took 1,273.37 seconds and is separate from the original throughput timing. Original baseline estimates are retained in data/analysis/baseline-v2.json.

## Tuning and knees

Knee: smallest worker count within 3% of the observed best. Confirmation stops after two successive rounds improve the previous best by less than 3%. Full-budget sustains use unrestricted scheduling; P/E affinity comparisons remain separate.

| Stage | Selected workers | Chunk | Affinity | Tuned units/min | Converged |
|---|---:|---:|---|---:|---|
| analysis | 12 | 1 | OS scheduler | 161.68 | True |
| corpus | 16 | 4 | OS scheduler | 361.10 | True |
| render | 16 | 1 | OS scheduler | 80.57 | True |
| synth | 16 | 1 | OS scheduler | 3,146.98 | True |

A selected count at the lane ceiling does not establish a hardware scaling plateau. The initial unrestricted sweeps still gained more than 3% at the largest allowed count for corpus, render and synth; those selections are budget-limited. Analysis gained only about 2.2% from 12 to 16 workers, so its observed worker knee is 12. Confirmation convergence concerns the best configuration's measured throughput, separately from worker-count scaling.

| Stage | Affinity class | Workers | Units/min | Host CPU mean % |
|---|---|---:|---:|---:|
| corpus | performance | 12 | 327.58 | 89.66 |
| corpus | efficiency | 10 | 175.95 | 89.93 |
| analysis | performance | 12 | 153.79 | 67.92 |
| analysis | efficiency | 10 | 130.02 | 62.49 |
| render | performance | 12 | 37.92 | 59.44 |
| render | efficiency | 10 | 37.26 | 76.79 |
| synth | performance | 12 | 2,222.74 | 87.76 |
| synth | efficiency | 10 | 1,548.57 | 66.08 |

Topology discovery: P=[0, 1, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19], E=[2, 3, 4, 5, 6, 7, 8, 9, 20, 21].

Every worker/chunk/affinity configuration and confirmation round is preserved in `data/cpu-peak/tuning/tuning.json`. Units are generated tracks, analyzed files, rendered recipes, or scored synth clips, respectively. The corpus tuning unit is a 20-second fresh track; analysis uses a complete corpus mix; render tuning uses a 10-second recipe; synth tuning scores one clip.

## Sustained CPU stages

| Stage | Workers | Seconds | Units/min | Host CPU mean / peak % | Tree RSS GiB | Host RAM GiB | Read / write MB/s |
|---|---:|---:|---:|---:|---:|---:|---:|
| corpus | 16 | 605.31 | 415.92 | 90.87 / 91.75 | 1.13 | 14.80 | 2.47 / 124.81 |
| analysis | 16 | 604.63 | 154.71 | 90.98 / 91.73 | 3.04 | 20.46 | 6.99 / 1.51 |
| render | 16 | 648.86 | 14.24 | 89.95 / 91.60 | 3.93 | 21.90 | 44.12 / 7.79 |
| synth | 16 | 601.19 | 2,382.47 | 77.09 / 91.71 | 2.06 | 20.09 | 22.39 / 8.38 |

| Stage | CPU temperature C | NVIDIA peak temperature C | NVIDIA observed throttle reasons |
|---|---:|---:|---|
| corpus | unavailable | 73.00 | none observed |
| analysis | unavailable | 85.00 | sw_power_cap |
| render | unavailable | 92.00 | hw_slowdown, hw_thermal, sw_power_cap, sw_thermal |
| synth | unavailable | 75.00 | none observed |

These are shared host/NVIDIA observations during each CPU measurement, not Intel device temperatures. The hardware thermal/power flags are logged under unleashed mode; they do not establish a CPU-stage thermal limit.


| Stage | NVIDIA observed samples | NVIDIA mean % | Samples above 90% | iGPU mean % |
|---|---:|---:|---:|---:|
| corpus | 21 | 0.00 | 0.00% | unavailable |
| analysis | 465 | 6.80 | 2.15% | 92.08 |
| render | 596 | 16.88 | 11.07% | 91.93 |
| synth | 572 | 6.99 | 0.00% | 92.71 |

NVIDIA overlap is observed through NVML or the existing Windows PDH adapter. NVML can report Unknown when idle; PDH zeroes are retained as zeroes. Missing/partial sampling cannot certify a synchronized ten-minute GPU run. NPU has no Windows utilization counter here; device execution and inferences/second are recorded directly.

Maximum observed configuration-average host disk rates: read 44.12 MB/s; write 124.81 MB/s. These are maxima across averaged measurement windows, not instantaneous NVMe device peaks.


Render sustain uses cross-source recipes with loudness matching and actual Rubber Band processing. Synth sustain evolves full populations with selection, crossover and mutation, saves each generation, and exposes a FitnessScorer protocol. The measured sustain used heuristic fitness; a separate single-parent CPU CLAP backend now supports trained taste fitness without duplicating the encoder in workers.

Full storm-recipe verification: True; duration 30.00 seconds. Two forced renders are compared with each other and the sustained-run output, not merely with a cached render.

Observed limits: analysis shows an early scaling plateau with full-track hashing, memory traffic and reads; the remaining CPU kernels continue gaining up to their allowed worker budget. Large host RAM occupancy and competing GPU/iGPU traffic were present, so these data do not isolate memory bandwidth from CPU, cache or disk latency. CPU thermals cannot be assigned as the limiter without a temperature reader. Every configuration and its concurrent host counters remain available for that distinction.

## Intel device runs

| Mode | Requested / executed | Device | Seconds | Embeddings/s | Reference max error | Fallback |
|---|---|---|---:|---:|---:|---|
| per-device | NPU / NPU | Intel(R) AI Boost | 600.01 | 45,527.93 | 0.000355 | none |
| per-device | GPU.0 / GPU.0 | Intel(R) Arc(TM) Graphics (iGPU) | 600.00 | 84,806.27 | 0.000497 | none |
| per-device | CPU / CPU | Intel(R) Core(TM) Ultra 9 185H | 600.00 | 91,697.89 | 0.000000 | none |
| simultaneous async | NPU / NPU | Intel(R) AI Boost | 600.07 | 145,476.69 | 0.000355 | none |
| simultaneous async | GPU.0 / GPU.0 | Intel(R) Arc(TM) Graphics (iGPU) | 600.07 | 92,173.74 | 0.000497 | none |
| CPU peak hold | NPU / NPU | Intel(R) AI Boost | 2,132.13 | 127,997.46 | 0.000355 | none |
| CPU peak hold | GPU.0 / GPU.0 | Intel(R) Arc(TM) Graphics (iGPU) | 2,132.13 | 53,080.95 | 0.000497 | none |

The IR is a seeded 512→256→64→1 ReLU MLP with static batch 128. It is an untrained synthetic load/placement probe, not the owner's taste model. Device compilation and numeric validation are excluded from sustained timing. Simultaneous mode feeds bounded asynchronous request queues from one host loop. Intel GPU full names are validated before compilation; NVIDIA execution is excluded.

## Limits and remaining work

CPU temperatures and thermal-throttle attribution require an available sensor reader. Host disk rates are aggregate OS counters, not lane-isolated bandwidth. Worker sweeps identify scaling limits; they cannot alone distinguish memory bandwidth, cache, power limits and thermal throttling. The GPU coordinator's combined bench record is needed to certify a synchronized all-engines result. A held GPU lock proves ownership, not sustained GPU utilization. See `docs/PEAK_REPORT.md` for the coordinator's evidence.

The late T-017 checkpoint failed validation: every parameter was nonfinite, as were all values in three sampled CLAP checkpoint files. FP16 autocast underflowed the log-mel floor. The front end now runs power/mel/log calculations in FP32; a new embedding/cache/index version isolates old artifacts. A real CPU CLAP forward produced finite features and a finite 512-dimensional embedding (data/verification/clap-fp32.json). The coordinator must restart embedding and retrain before the production checkpoint can be used. Recovery is tracked in T-022. Old artifacts are retained.

Trained OpenVINO export and synth fitness adapters preserve the trainer's exact GELU, biases, sigmoid and CLAP version. Fixture tests compare NumPy/OpenVINO predictions with PyTorch. Automatic selection warns and retains the labeled random/heuristic backend when weights are invalid; explicit trained selection fails. No learned-throughput result is claimed from corrupt weights. Training rejects nonfinite inputs/loss/weights and replants current-version synthetic ratings when only old-version ratings exist.

## Verification and handoff

Repository suite: 239 passed, 1 skipped, 1 deselected. The skipped browser extra and separately marked scale test remain distinct from CPU/NPU verification. Exact 30-second render reproduction and deterministic evolutionary resume are checked. CPU/NPU locks were released for the coordinator's T-018 run. No new user blocker was introduced; existing optional power-mode, merge-worktree cleanup and idle-time environment sync are listed in docs/NEEDS_USER.md.

## Reproduce

```powershell
uv run remixer corpus generate --n 500 --legacy-arrangement
uv run remixer analyze
uv run remixer analyze --queue
uv run remixer cpu tune --output data/cpu-peak/tuning
uv run remixer cpu sustain --output data/cpu-peak/sustain --tuning data/cpu-peak/tuning/tuning.json --seconds 600
uv run remixer npu --seconds 600 --random-scorer
uv run python tools/corpus/report.py
uv run pytest
```

Acquire CPU/NPU locks through agentctl before heavy runs; the peak coordinator acquires GPU, CPU, NPU in that order. Use REMIXER_DATA_DIR for an alternate data root. Source music remains read-only.

## Versions

- numpy: 2.4.6
- scipy: 1.17.1
- soundfile: 0.14.0
- pyarrow: 26.0.0
- pedalboard: 0.9.26
- pyloudnorm: 0.2.0
- openvino: 2026.4.1

![CPU worker and chunk scaling](cpu-lane-scaling.png)

Curves show median repeated measurements for each worker/chunk pair; stars show the selected best observed result. Concurrent GPU activity and memory pressure changed during the sweep, so this is an operational scaling record rather than an isolated processor scaling law.


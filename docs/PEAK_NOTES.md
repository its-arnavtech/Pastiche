# Peak notes (T-018)

Hand-written narrative; `remixer bench report` copies it into `docs/PEAK_REPORT.md` above the computed tables.

Machine: ASUS laptop, Intel Core Ultra 9 185H (22 logical CPUs), RTX 4060 Laptop 8 GB, Intel Arc iGPU, Intel AI Boost NPU, 23.4 GiB RAM. Plugged in, Windows power mode "Best performance" (overlay on the Balanced plan) from round 2 on; round 1 ran under Balanced.

## Plain verdict

This laptop is limited by heat, not by any one engine. The CPU and the RTX 4060 share one cooling system:
- **CPU alone:** with the GPU idle, 8 render workers hold a 3.6-4.0 GHz effective clock.
- **CPU next to a busy GPU:** the same CPU falls to about 1.1 GHz, and the ACPI CPU zone sits at its 95.9 C ceiling.
- **GPU:** spends 88-97 % of samples under `sw_thermal` clock limiting at about 55 W, far below its power cap.

What you can expect:
- **GPU on its own (Demucs):** about 60-66 audio-seconds of separation per second.
- **Everything on at once:** the GPU keeps about 58 audio-s/s; the CPU render lane falls from about 12.6 to about 3 rendered audio-s/s.

Two uncapped attempts under Best performance powered the machine off (System event 6008, see below). Every number below "Final configuration" is what the machine sustains without shutting down.

**Pass condition:** GPU > 90 % while the CPU lane stays near saturation. It is **not met at the same time** in any configuration; it is a trade:
- **6 CPU workers:** the GPU averages 90.2 %, but the CPU lane's own cores only 75 %.
- **10 workers:** the CPU lane's cores reach 95 %, but the GPU drops to 86 %.

Tuning converged: the last two rounds moved the score by -1.3 % and +1.1 %.

**Did the GPU stay above 90 % in the combined run?**
- **60-minute combined sustains:** yes. Round 1 averaged 94.0 % and round 2 94.0 %.
- **But round 2's 94 % has a catch:** the thermal watchdog paused the CPU and NPU lanes for the last 22 minutes. The GPU's 90 C trigger was below its own steady state; that was fixed in round 3.
- **Tuned configuration:** the GPU averages 89.2 % with no pauses (78 % of samples at or above 90 %).
- **Starvation:** no starvation event (GPU < 80 % with an empty feeder queue) was logged in any capped or tuned run. The only one ever came from crashed attempt 2.

## Per-engine peaks

| Engine | Workload | Best isolated (90 s) | Best with all lanes on, 90 s | Sustained, all lanes on | Limited by |
|---|---|---:|---:|---:|---|
| RTX 4060 (CUDA) | Demucs htdemucs, light | 66.61 audio-s/s (batch 8, 6 pinned feeder CPUs, round 2) | 62.46 audio-s/s (round 2) | 59.74 audio-s/s for 60 min (round 2); 58.40 for 15 min (final config) | GPU thermals: 86 C mean / 93 C max, `sw_thermal` 88-97 % of samples, about 55 W mean of its power budget; SM 1.9 GHz mean |
| RTX 4060 (CUDA) | Demucs htdemucs_ft, 2 shifts (8 passes per audio second) | - | - | 58.62 model-pass audio-s/s = 7.33 audio-s/s for 60 min (round 1) | Same thermal ceiling; same per-pass rate as light, so heavy costs exactly 8x |
| CPU, 14 pinned logical CPUs | Rubber Band render storm (stretch, shift, mix) | 13.66 rendered audio-s/s at 16 workers (round 1, Balanced); 12.64 at 8 workers (capped) | 12.48 (round 1, 16 workers) | 3.15 (10 workers), 2.89 (8, final), 2.46 (6) | Shared cooling: CPU zone 95.9 C, effective clock about 1.0-1.2 GHz once the GPU is busy |
| Intel NPU (OpenVINO) | Taste scorer, batch 128 | 50,685 inferences/s (NPU only) | 65,311 (NPU only, round 2); 114,497 (NPU + iGPU, round 1) | 47,447 (NPU only, 15 min); 13,592 (NPU + iGPU, 60 min, round 1) | Host-side feeding on one LP-E core; the iGPU shares the CPU package's power and heat budget and collapses under load |

Other GPU engines, measured on their own outside the stress bench:
- **MusicGen generation:** 5.19 audio-s/s, 1.74 GiB VRAM.
- **CLAP re-embed:** 135 windows/s at batch 16.
- **Trained taste-scorer export (short runs):** NPU 122,253 inferences/s, iGPU 492,934.

Resource maxima across all runs:
- **VRAM:** 7.93 GiB of 8, during the round-1 GPU ramp at batch 10. Capped runs stayed at or below 5.3 GiB.
- **RAM:** 22.84 of 23.4 GiB, with swap up to 1.9 GiB. RAM is the next wall after heat.
- **Disk:** 808 MB/s read, 1181 MB/s write. Disk was never a limit.

## Final configuration

`remixer bench stress --sustain 15m --cool --gpu-mode cycle --gpu-limit-c 94` (round 3, the best score, 1.862 x round 1):

- **Core split:** GPU lane on logical CPUs 0-5, at above-normal priority (the first P-core's threads plus feeder E-cores). CPU render lane on 6-19. NPU host on 20; 21 is kept free.
- **GPU lane:** batch 8, light htdemucs, corpus cycle. The heavy htdemucs_ft model is off, because it draws the most power for the same pass rate.
- **CPU lane:** 8 render workers.
- **NPU lane:** NPU only. The iGPU is off, because it competes with the CPU for package power.
- **Thermal watchdog:** pauses the CPU and NPU lanes when the 10 s median of the CPU zone is at or above 97 C, or the GPU is at or above 94 C. It resumes 8 C lower.
- **Cooldown:** before every step, wait until the CPU zone is below 82 C.

If GPU utilization matters more than render throughput, use `--cpu-max-workers 6`. The score is within 1.3 %, and the GPU averages 90.2 %.

**Preset note (decision 0030):** this configuration is now the default preset (`stable` in `profile.yaml`): 8 CPU workers, light Demucs with batch up to 8, NPU only, thermal watchdog on. The old uncapped settings need an explicit `--unleashed`, which prints a warning. The preset's CPU cutoff is 93 C, not the 97 C used in the rounds above: the zone tops out at 95.9 C, so 97 C could never fire. The numbers in this report were measured with 97 C; the 93 C cutoff has had no sustained run of its own.

## Rounds and what each changed

| Round | Run | Change | Outcome |
|---|---|---|---|
| 1 | 20261029-001335 | Unleashed, unpinned, Balanced power mode, ramp + 60 min | Survived. GPU 94 %. CPU lane oversubscribed (GPU process about 5.4 cores, plus 16 workers, plus NPU host), falling to 2.42 rendered audio-s/s |
| crash 1 | 20261029-093611 | Pinned lanes, Best performance, unleashed | GPU ramp finished (49.2 / 59.2 / 63.7 / 65.2 audio-s/s); the laptop powered off at the start of the CPU ramp (4 workers) |
| crash 2 | 20261029-095035 | Same | GPU ramp finished (47.2 / 58.5 / 63.5 / 64.3); CPU at 4 workers gave 6.25; powered off at 7 workers |
| 2 | 20261029-123752 | `--cool` caps, watchdog and cooldown; ramp + 60 min (sustain at the ramp's combined knee: 6 CPU workers) | Survived. The GPU's 90 C trigger paused the CPU and NPU lanes for the last 22 min, so CPU was 1.43 |
| 3 | 20261029-142810 | GPU trigger 90 -> 94 C | No pauses. CPU 2.89, NPU 46.1k. Score +40.8 % |
| 4 | 20261029-144502 | CPU workers 8 -> 6 | GPU util 90.2 %, CPU 2.46. Score -1.3 % |
| 5 | 20261029-150303 | CPU workers 8 -> 10 | CPU-lane cores 95 %, GPU util 86 %, CPU 3.15. Score +1.1 %. Converged |

Throttle and temperature events:
- **GPU:** `sw_thermal` the whole time in every sustained run. `hw_thermal`, `hw_slowdown` and `sw_power_cap` each stayed at or below 0.4 % of samples.
- **CPU:** the zone holds 94-96 C under any sustained load. The 97 C watchdog never fired, because the zone tops out at 95.9 C.
- **Watchdog and cooldowns:** the only watchdog pause was round 2's GPU-triggered one. Cooldowns before steps took 10-301 s.
- **Unexpected shutdowns:** the two crashed attempts, recorded in System event 6008. The cause is inferred as CPU heat and power under Best performance after the GPU ramp. Firmware limits can't be read without admin tools; see `docs/NEEDS_USER.md` item 4.

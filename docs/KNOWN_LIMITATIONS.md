# Known limitations (end of POC 1)

Honest list, most important first. Effort: **S** under half a day, **M** one to three days, **L** more than three days.

## The ones you asked about

### 1. Per-stem effects are not applied by the renderer, so patch re-renders cannot apply them either
The planner gives vocals a reverb (`reverb_mix 0.15`) and the harmonic stem a high-pass (`highpass_hz 120`)
(`PlannerConfig.effects`). The renderer (`cpu/render.py`) only has mix-level gain, filter and delay, so `cpu/patch_render.py` records
every such effect under `unapplied_effects` in the manifest and renders without it. Full renders and patch renders ignore the
same effects, which is why a patched render still equals a full render of the new version. In the demo: 31 effect entries not applied.
- **Impact:** recombined tracks sound drier and less polished than the recipe intends. Reproducibility and the "only affected sections" guarantee are unaffected.
- **Fix:** apply per-stem effects with Pedalboard before the mix, and put the effect parameters into the render cache key (they are already in the section hash). Extend `test_patch_render` so patch equals full render with effects on.
- **Effort:** M.

### 2. The local insight model (`qwen3:4b`) is weak
It garbles the `window_id` strings it must echo in about half of Analyst and Skeptic replies (decision 0028). The pipeline rejects those and falls back to its deterministic rules, which kept precision at 1.0 on the confound fixture, so insights are
safe but are mostly rule-written, not model-written. The demo uses a deterministic `MockLLM` by default (`remixer demo --llm ollama` uses the real model); the Ollama server was not running while this was written.
- **Fix, cheap:** have the model echo a short index instead of the full window id (insight layer change, no new model).
- **Fix, bigger model:** `llama3.1:8b` or `qwen3:8b` at Q4_K_M need about 5-5.5 GB of VRAM. Demucs at batch 8 peaks at about 5.3 GiB of the 8 GB card (`docs/PEAK_REPORT.md`), so **an 8B model cannot sit next to Demucs**. It fits when Demucs is unloaded, which suits the nightly job: the spec already says the scheduler must serialize or swap them. Keep a model of 4B or smaller (about 2.5 GB) for anything that must run beside Demucs. Both candidate 8B models have licenses with conditions (`docs/licenses.md`); `qwen3:8b` is Apache-2.0. Pulling a model is a download the agents did not make.
- **Effort:** S for the index change, S to M for the swap-aware scheduling (load Ollama after the GPU lock is free, unload before the next separation).

### 3. The nightly insight job is not scheduled
`remixer insights nightly` runs once per local night (after 03:00), but nothing runs it. Registering a Windows scheduled task is a persistent system change, so the agents left it (`docs/NEEDS_USER.md`, item 5). Until then insights appear only when someone runs the command.
- **Fix:** run the `schtasks` command in `docs/NEEDS_USER.md` once; make sure Ollama is up at that hour. The job skips the night, harmlessly, if the model is down.
- **Effort:** S (user).

### 4. Browser tests run on Microsoft Edge, not Playwright's Chromium
Playwright 1.64 wants Chromium build 1248 and only 1194 is cached, so the fixture falls back to the system Edge (`channel="msedge"`) (decision 0029). Passing on Edge is real evidence but is not the headless build CI would use, and an Edge update can change behaviour.
- **Fix:** `uv run playwright install chromium` (a download of about 150 MB from Microsoft's CDN).
- **Effort:** S (user).

### 5. The CPU and the GPU share one cooling system, so the "both engines saturated" condition cannot be met together
The pass condition (GPU above 90 % while the CPU lane stays near saturation) is a trade-off, not a pass: 6 CPU workers give the GPU 90.2 % with the CPU lane at 75 %; 10 workers give the CPU lane 95 % and the GPU 86 %. Uncapped runs powered the laptop off twice. Details: `docs/PEAK_REPORT.md`, decisions 0025 and 0026.
- **Fix, hardware:** fan profile, clear vents, a cooling pad, the original charger (`docs/NEEDS_USER.md` item 4). Not a software change.
- **Fix, software:** time-slice the lanes instead of running both flat out (the render lane is only 3 rendered audio-seconds per second while the GPU is busy, against 12.6 when it is not).
- **Effort:** S (user) or M (time slicing).

## Things the stable preset did not get to prove

### 6. The final tuned configuration never had its own 60-minute sustain
The 60-minute combined sustains were rounds 1 and 2. Round 2's catch: the thermal watchdog paused the CPU and NPU lanes for the last 22 minutes. The tuned configuration (rounds 3-5) was run for 15 minutes each, with no pauses. The new default also moved the CPU cutoff from 97 C to 93 C, and no run has used 93 C. Decision: no more stress benchmarking.
- **Fix:** one 60-minute `remixer bench stress --sustain 60m` under the stable preset, with the laptop on its good charger.
- **Effort:** S of attention, one hour of machine time. Do it only when you accept the risk.

### 7. Outside `bench stress`, the thermal guard only logs
In stable mode `Guard` reports `reduce` when the 10-second median CPU zone reaches 93 C, but nothing consumes `Decision.scale`. Only the bench watchdog pauses lanes. A long `separate`, `embed` or CPU job on a hot laptop is therefore capped by the stable preset's worker and batch limits, not by temperature.
- **Fix:** have the worker loops lower their worker count or batch when `scale < 1`, or reuse the bench watchdog's suspend/resume for them.
- **Effort:** M.

### 8. The sensor is the ACPI zone `_TZ.THRM`, not a real package sensor
It needs no admin rights but spikes 15-20 C even at idle, tops out at 95.9 C, and has no hardware documentation here. All thermal logic uses a 10-second median. LibreHardwareMonitor would give a proper reading and is used automatically if it runs. NPU utilization is not exposed by Windows at all.
- **Effort:** S (install LibreHardwareMonitor and enable its web server).

## Product gaps

### 9. Real ratings do not retrain the taste model
A rating in the player reaches fatigue and the next batch immediately (`docs/ACCEPTANCE.md`, real-use path). But `remixer taste --real` trains on `rating_events` rows with `target_kind='window'`, and the player writes `source` and `track` rows. Nothing maps a track or stem rating to the 5-second windows that were audible. Until it does, the taste model stays at its synthetic training and real taste enters only through fatigue and dislikes.
- **Fix:** credit a rating to windows by loudness share and playback position (the credit code exists) and write window rows with `synthetic=0`.
- **Effort:** M.

### 10. No real music has been run through the pipeline
All pipeline evidence is on the synthetic corpus (500 tracks, 29.9 hours) and the demo. A real library has been scanned read-only in tests, never separated. Demucs quality on real music, tempo and key accuracy on real music, and the planner's choices on real stems are unverified.
- **Fix:** point `remixer ingest --library <folder>` at a small folder and run the stages.
- **Effort:** S (user), plus tuning once real results exist.

### 11. The planner's 5 % per-song cap needs a big library
The cap is `floor(slots x 0.05)` stems per song. A batch of 64 slots allows 3 stems per song, so 20 songs can fill at most 60 slots. The demo therefore uses a 15 % cap. A real library of a few hundred songs keeps the default.
- **Effort:** none for the real case; a library under 100 songs should lower the number of recipes per batch.

### 12. Registering embeddings is not atomic
The embedder inserts the stem row, then each window row, then the vector index. A kill between those inserts can leave a stem with some windows missing, and the resume check (stem row exists) will not repair it. The demo's forced kill found and fixed the larger case (finished stems or vectors never registered at all); this narrower window remains.
- **Fix:** write the stem row last, or wrap the registration in one transaction.
- **Effort:** S.

### 13. Smaller things
- Windows paths over 260 characters: the section cache's file names are about 100 characters, so a deep output directory fails. `remixer demo --out` needs a short path. **Fix:** shorter hashed names. S.
- The Parquet event sink writes one part file per POST; it needs compaction for more than one listener. S to M.
- The `remixer demo` default uses a deterministic mock LLM and, in `--fast` mode (tests only), stub embeddings.
- The demo kills the separation worker at a fixed point (after 4 finished tracks) once; random kill testing is not automated.
- Phase 5 (generative layer): MusicGen weights are non-commercial (`docs/licenses.md`) and ran only as a GPU-load stretch.

## Commercial profile (paper only)
No commercial adapters, no thin slice, no per-tenant cost events, no quotas. Four places in the core assume local storage or SQLite (`docs/commercial.md`). The legal path is undecided (`docs/legal-paths.md`).

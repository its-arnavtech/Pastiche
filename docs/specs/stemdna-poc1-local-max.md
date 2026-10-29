# StemDNA POC 1: Local Max (Claude Code Build Spec)

You are building the first proof of concept of StemDNA: a pipeline that separates a music library into stems, learns the owner's taste, and assembles new tracks from recombined stems. This POC runs entirely on one Windows laptop and deliberately saturates CPU, GPU, NPU, RAM and disk.

Build the core so it can later run in a commercial profile (see POC 2). That means core logic depends on interfaces, never on this machine. Do not reference or reuse any other existing project. This is standalone.

---

## 0. Target machine

- ASUS Vivobook Pro, Windows. Core Ultra 185H (16 cores: P, E and LP-E), Intel Arc iGPU, Intel NPU, RTX 4060 Laptop GPU (8 GB VRAM), NVMe SSD.
- A backup laptop exists, so this machine may be pushed hard. Keep only a minimal watchdog (section 7) to avoid a hard shutdown or data loss. No cooldown schedules, no power caps.
- 8 GB VRAM is the real ceiling. Everything GPU-side must fit in it (fp16, small models, batch sizing by measured free VRAM).

## 1. Architecture principles

- **Core vs adapters.** Core logic (recipes, event log, fatigue model, skip analytics, selection) depends only on interfaces. Adapters implement them per profile.
- **Interfaces to define up front:** `BlobStore`, `Catalog`, `EventSink`, `VectorIndex`, `JobQueue`, `ComputeBackend`, `LLMClient`.
- **Local adapters (this POC):** filesystem, SQLite, Parquet + DuckDB, FAISS or hnswlib, a SQLite-backed durable job table plus multiprocessing, local GPU, Ollama.
- **Config-driven.** One `profile.yaml` selects adapters and resource limits. No hardcoded paths or machine assumptions in core code. Windows-specific calls live in adapters only.
- **Idempotent, resumable, content-addressed.** Every stage can be re-run safely. Artifacts are keyed by content hash plus model version.
- **Append-only events.** Never update history. Derived state (fatigue, heatmaps) is recomputed from events.
- **Tracks are recipes.** A generated track is stored as a recipe (which stems, which time ranges, tempo, key, effects, seed). Audio is a render of a recipe and can be re-rendered.

## 2. Suggested stack

Python 3.11 managed with `uv`. Demucs, PyTorch (CUDA), librosa, Pedalboard (time-stretch and pitch-shift), transformers (CLAP or MERT), FAISS or hnswlib, DuckDB + Parquet, SQLite, FastAPI + a plain HTML/JS player, OpenVINO (NPU/iGPU), Ollama (phase 4), pynvml + psutil. Prefer native Windows; use WSL2 only if a dependency requires it, and note why in `NOTES.md`.

## 3. Pipeline stages

1. **Ingest:** scan library, fingerprint (content hash), read tags, dedupe, register in catalog.
2. **Separate:** Demucs (htdemucs) into drums, bass, vocals, other. Cache by (content hash, model version). GPU stage; batch by free VRAM.
3. **Analyze:** per track and per stem: tempo and beat grid, key, loudness (LUFS), energy curve, 5-second window features. CPU stage, parallel across all cores.
4. **Embed:** audio embeddings per stem and per 5-second window. GPU stage. Store in the vector index.
5. **Taste model:** scores any stem, window, or recipe against the owner's taste from ratings. Start simple (logistic regression or small MLP on embeddings). Retrain in batch.
6. **Assemble:** the remixer picks compatible stems (key, BPM, embedding fit, taste score, fatigue, novelty), time-stretches and pitch-shifts them, mixes with loudness matching, and emits a recipe plus a render.
7. **Playback and events:** local web player with the event log in section 5.
8. **Analytics and insights:** nightly batch builds fatigue and skip heatmaps, then (phase 4) runs the agent layer.

Selection weight: `taste_score x (1 - fatigue) x novelty_bonus`, with a per-batch cap so no single source song contributes more than about 5 percent of stems.

## 4. Feedback model

- **Ratings are user-initiated only.** The system never prompts or asks "did you like this?". Every track, source song and stem has a persistent rating control: thumbs up, thumbs down, and a separate "tired of this" flag (temporary, decays) distinct from dislike (permanent).
- **Credit assignment:** a rating on a generated track is distributed across the stems that were audible, weighted by each stem's loudness share. Window-level when the signal is window-specific.
- **Statistical attribution:** a regularized (ridge or Bayesian logistic) model over stem presence vs rating isolates culprit stems over time.
- **Embedding-neighbor propagation:** a negative on a stem applies a smaller penalty to its nearest neighbors (tired of the sound, not the song).
- **Fatigue is a decaying state** (exponential decay), so a rested song can return.
- **Retroactive cleanup:** banning a song flags every recipe containing it. Swap in the nearest replacement stem (key, BPM, embedding) and re-render only affected sections.

## 5. Playback events and skip analytics

Controls: play, pause, seek -5s, seek +5s (fixed, never other sizes), next track, previous track, track end.

Event schema (append-only): `event_id, session_id, track_id, track_version, event_type, position_ms, wall_time, source_kind (source|generated), client_info`. `track_version` pins events to the exact audio, since recipes can be re-rendered.

Interpretation rules:
- **Skip burst:** several +5s presses within about 2 seconds count as one skip of N x 5s.
- **Undo:** a -5s soon after a +5s means the user overshot. Cancel the skip (neutral or mildly positive). This covers "the skipped part led into something good".
- **Replay:** a -5s into a region just heard is a positive signal for that window.
- **Next:** early next is a track-level negative or fatigue signal; next near the end is no signal. Previous is a positive for that track.

Heatmap:
- Bin each track into 5-second windows. Per window count `played, skipped, replayed, undone`.
- The denominator is the number of listens that actually reached that window, not total listens.
- A window becomes a candidate only if: at least 3 listens of the track, skipped in a clear majority of the listens that reached it, and undo events are rare.

Passive signals feed analytics only. They never trigger a prompt.

## 6. Saturation design (the point of this POC)

- **GPU (RTX 4060):** Demucs and embeddings keep it near 100 percent. Auto-size batches to free VRAM; keep fp16; keep the work queue non-empty so the GPU never idles waiting on disk or CPU.
- **CPU (all cores):** analysis, window features, resampling, time-stretch renders and dataloading run in a process pool sized to the logical core count minus a reserve of 1 to 2 cores, so the OS and player stay responsive.
- **NPU / iGPU (OpenVINO):** run the small taste scorer and similarity scoring there, in parallel with GPU work. Optional; fall back to CPU if export fails.
- **RAM / disk:** memory-mapped stem cache, prefetching, large sequential reads and writes. Log throughput.
- **Pipeline overlap:** stages run concurrently as a streaming pipeline (separate, analyze, embed), not in sequential batches.
- **LLM (phase 4):** the local LLM competes with Demucs for VRAM. The scheduler must serialize them or swap with explicit load and unload.

## 7. Telemetry and watchdog

- Sample every 1 to 2 seconds: GPU util, VRAM, GPU temp and power (pynvml), per-core CPU util, RAM, disk throughput, and CPU temp. CPU temp on Windows needs an external reader (LibreHardwareMonitor or HWiNFO shared memory); make it optional.
- Write telemetry to Parquet and chart it on a simple dashboard page.
- Watchdog (minimal): if CPU > 98 C or GPU > 90 C sustained for 30+ seconds, reduce worker count and batch size until it recovers, and log every intervention.
- Checkpoint after each unit of work so a crash or reboot loses at most one item.

## 8. Benchmark command

`stemdna bench --stress` runs the full stage mix on a sample library for a fixed duration and prints a utilization report. Use it to prove saturation.

## 9. Data model (minimum)

`tracks, stems, windows, embeddings (vector index), recipes, recipe_stems, renders, rating_events, playback_events, stem_exposure, stem_fatigue (derived), insights, jobs, telemetry`.

## 10. Acceptance criteria

- Process a library of at least 200 tracks end to end, resumable after a forced kill.
- During a sustained stress run: GPU util mostly above 90 percent, CPU util mostly above 90 percent, no OOM, no data loss.
- Remixes are reproducible: same recipe plus seed gives an identical render.
- The player logs every control in section 5; the heatmap detector is correct on a synthetic event set with known skip patterns, including the undo and burst cases.
- Banning a song flags dependent recipes and re-renders only the affected sections.

## 11. Phases

1. **Foundation:** repo, interfaces, profile config, catalog schema, ingest, job queue, telemetry skeleton.
2. **Separation, analysis and embedding pipeline,** streaming, resumable, with the stress benchmark.
3. **Taste model, assembler, recipes, player, event log, fatigue, skip-heatmap detector.**
4. **Agent layer (local LLM):** Analyst proposes a hypothesis for each candidate window; Skeptic checks confounds (long intros, mood or time of day, shuffle context); Narrator writes the plain-language insight. Insights go to a passive inbox (never interrupt playback, about one per day) with "Yes, skip it from now on", "No, I like it", and "Not sure yet". Insights affect the remixer only after the user confirms. Answers tune detector thresholds.
5. **Generative layer (optional):** a LoRA-tuned small music model and an evolutionary synth renderer (software-generated note sequences, no physical instrument or MIDI keyboard needed) to push saturation further. Check model licenses first.

## 12. Working rules for Claude Code

- Start with phase 1 and a short plan. Ask before any decision that is hard to undo.
- Write tests for event interpretation and heatmap logic before the UI.
- Keep core code free of machine-specific paths and Windows-specific calls; isolate them in adapters.
- Pin model versions and record them in every artifact's metadata.
- Commit in small steps with clear messages. Keep a `NOTES.md` of decisions and open questions.
- Do not add features beyond this spec without asking.

# Pastiche (codename StemDNA)

Pastiche separates a music library into stems (drums, bass, vocals, other), learns what its owner likes from ratings and
skips, and assembles new tracks by recombining stems. A generated track is stored as a **recipe** (which stem, which time
range, tempo, key, effects, seed); the audio is a render of the recipe and can be re-rendered, so banning a song re-renders only
the sections that used it. POC 1 (this repository, tag `v0.1-poc1`) runs on one Windows laptop and deliberately drives its GPU,
CPU, NPU and disk to find the machine's peak. The Python package is `remixer`.

Status: POC 1 is complete. See `docs/ACCEPTANCE.md` (every acceptance criterion with evidence), `docs/KNOWN_LIMITATIONS.md`
(what is not done) and `docs/PEAK_REPORT.md` (what the machine sustains).

## Architecture

```
 music library (read-only)  or  synthetic corpus
            |
        [ingest]  hash, tags, dedupe ---------------> Catalog (SQLite)        tracks, stems, windows, analysis,
            |                                                                 embeddings, recipes, renders, ratings
   [separate]  Demucs htdemucs, GPU lane --- stems --> BlobStore (files)
            |
   [analyze]   tempo, key, LUFS, 5 s windows, CPU lane (process pool)
            |
   [embed]     CLAP per stem and window, GPU lane ---> VectorIndex (hnswlib)
            |
   [taste]     MLP on embeddings (GPU train, NPU score)
            |
   [plan]      Planner: taste x (1 - fatigue) x novelty, key/BPM compatible, per-song cap  --> RecipeStore + Lineage
            |
   [render]    section-cached Rubber Band stretch/shift + mix, CPU lane ----> renders (audio)
            |
   [player]    FastAPI backend + plain HTML/JS player; every control logged --> EventSink (Parquet)
            |
   [analytics] skip bursts, undo, replay, 5 s heatmap, fatigue (decaying), credit assignment
            |
   [insights]  nightly: Analyst, Skeptic, Narrator (local LLM) --> passive inbox; answers tune thresholds
            |
   ban / rating --> exclusions + fatigue --> next batch; patch re-renders only the changed sections
```

Core logic depends on seven interfaces (`BlobStore`, `Catalog`, `EventSink`, `VectorIndex`, `JobQueue`, `ComputeBackend`,
`LLMClient`, in `src/remixer/interfaces.py`); `src/remixer/adapters/` implements them for this laptop. Contract tests in
`tests/contracts/` define what any other implementation must do. Everything is idempotent, resumable and content-addressed;
events are append-only and fatigue and heatmaps are always derived from them.

## Install

Windows, Python 3.11, [uv](https://docs.astral.sh/uv/). A CUDA GPU is needed for separation and embedding (the PyTorch CUDA 13 build is
configured in `pyproject.toml`); an Intel NPU is optional.

```bash
git clone https://github.com/its-arnavtech/Pastiche.git
cd Pastiche
uv sync --extra analytics --extra player --extra web-test
uv run remixer info          # profile, mode, lane budgets, devices
uv run pytest                # the full suite
```

Optional: Ollama with `qwen3:4b` for the insight layer; `uv run playwright install chromium` for the bundled browser (the tests
fall back to the system Edge).

## Run the demo

```bash
uv run remixer demo
```

About three minutes under the stable preset. It generates 20 synthetic tracks and runs the whole loop: ingest, Demucs separation
(with one forced kill and resume), analysis, CLAP embedding, taste, planning and rendering of 4 recipes, the real player backend,
a scripted listening session (single skip, burst, undo, replay), the heatmap, an insight in the inbox, ratings that change the next
batch, and a song ban that re-renders only the affected sections. Output lands in `reports/demo/` (`demo.log`, `DEMO.md`,
`summary.json`, `audio/*.flac`, `heatmap.png`, `logs/`). It uses its own data directory, never `data/`.
`remixer demo --fast` replaces the GPU stages with stubs (tests only).

To play with the player yourself: `uv run remixer serve --demo --port 8765`, then open http://127.0.0.1:8765/.

## Presets and lanes

| Preset | How | What it does |
|---|---|---|
| **stable** (default) | nothing | 8 CPU render workers, light Demucs (`htdemucs`) with batch up to 8, NPU only (no iGPU), thermal watchdog: CPU zone 93 C, GPU 94 C (10 s medians), 82 C cooldown between bench steps. This is the configuration that survived the laptop shutdowns |
| unleashed | `remixer --unleashed ...` | No caps, no watchdog. Prints a warning: two uncapped runs powered this laptop off |
| safe | `remixer --safe ...` | Conservative guards: pause on battery, reduce at GPU 90 C / CPU 100 C |

Lanes run concurrently and are budgeted from the real core count (`config/resources.yaml`): the **GPU lane** (Demucs, CLAP, taste
training; exclusive, 4 feeder cores), the **CPU lane** (analysis, rendering, synthetic corpus; capped at 8 workers by the stable
preset) and the **NPU lane** (OpenVINO taste scorer; 1 host core). The runtime profile is `profile.yaml`; the stable settings live
in its `stable:` block (decision 0030). Heavy runs take a lock first: `python scripts/agentctl.py lock acquire gpu --owner <id>`.

## Commands

`remixer info | resources | demo | serve | ingest | separate | embed | taste | analyze | assemble | render | corpus | synth | npu |
telemetry | bench stress|report | insights nightly`. Use `remixer <command> --help`.

## Where things are

| What | Where |
|---|---|
| Acceptance verdict with evidence | `docs/ACCEPTANCE.md` |
| Peak results (what this machine sustains) | `docs/PEAK_REPORT.md`, narrative in `docs/PEAK_NOTES.md`, raw runs in `reports/peak/<run>/` |
| CPU and Intel lane measurements | `docs/reports/cpu-lane.md` |
| Demo output | `reports/demo/` |
| Known gaps with fixes and effort | `docs/KNOWN_LIMITATIONS.md` |
| Things only the owner can do | `docs/NEEDS_USER.md` |
| Decisions | `docs/decisions/` |
| Changelog | `CHANGELOG.md` (generated from `changelog/`) |
| Specs | `docs/specs/stemdna-poc1-local-max.md` (built), `docs/specs/stemdna-poc2-commercial.md` (paper only) |
| POC 2 paper design | `docs/commercial.md`, `docs/unit-economics.md`, `docs/licenses.md`, `docs/legal-paths.md`, `docs/deployment.md` |
| Hardware and tool facts | `docs/ENVIRONMENT.md` |
| Agents' working rules | `AGENTS.md` |

## Rules worth knowing

The owner's music is strictly read-only: it is hashed and read in place, never modified, moved or uploaded. Synthetic and real data
never mix (separate planners, fatigue, taste checkpoints and rating rows per origin). Ratings are user-initiated only; the system
never asks "did you like this?". Data lives in `data/` (git-ignored, override with `REMIXER_DATA_DIR`).

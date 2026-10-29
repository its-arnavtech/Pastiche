# Model, dependency and data licenses

**This is a working inventory, not legal advice.** It exists so that no model or library ships in a commercial profile by
accident (POC 2 spec section 5). Review it with someone qualified before any public launch (`docs/legal-paths.md`).

How each license was established:

- **Installed** = read from the package metadata in this repository's virtual environment (`importlib.metadata`), 2026-10-29.
- **Card / upstream** = recalled from the project's model card or repository. Not re-fetched while writing this, so re-check the
  exact version before relying on it.

"Commercial use?" is a first reading of the license text, with the conditions that matter. **NON-COMMERCIAL** and **COPYLEFT**
rows are the ones to resolve before a commercial launch.

## Models

| Model | Used for | License | Basis | Commercial use? |
|---|---|---|---|---|
| Demucs v4 `htdemucs`, `htdemucs_ft` (code and weights) | stem separation | MIT | Installed (`demucs` 4.1.0: MIT); weights: upstream repository says MIT | Yes. Check the training-data terms (MUSDB18-HQ and extra songs) if provenance matters to a buyer |
| CLAP `laion/clap-htsat-unfused` | audio embeddings | Apache-2.0 | Card / upstream | Yes. The training data (LAION-Audio-630K) mixes sources; its terms were not reviewed |
| MusicGen `facebook/musicgen-small` weights | T-019 stretch GPU load only; output discarded | **NON-COMMERCIAL: CC-BY-NC-4.0** | Card / upstream | **No.** Local benchmarking only. Must not ship in the commercial profile or touch a product code path |
| `qwen3:4b` (via Ollama) | insight layer on this laptop | Apache-2.0 | Card / upstream | Yes |
| `llama3.1:8b` / `llama3.2:3b` (named as upgrade options) | insight layer | Llama community licenses | Card / upstream | Conditionally: attribution and naming rules, an acceptable-use policy, and a large-company threshold. Read before shipping |
| Trained taste MLP (`taste-mlp-v1`) | taste scoring | the project's own; trained on synthetic ratings so far | In-repo | Yes. A model trained on real users' ratings is user data (see `docs/legal-paths.md`) |

## Code dependencies (runtime)

| Package | Version | License | Basis | Commercial use? |
|---|---|---|---|---|
| **pedalboard** (Spotify) | 0.9.26 | **COPYLEFT: GPL-3.0** | Installed | Server-side use does not by itself oblige source release under the GPL (it is not the AGPL), but **shipping it to users (desktop app, mobile, bundled build) does**. It also provides the Rubber Band time-stretch and pitch-shift the renderer depends on, and Rubber Band is dual-licensed (GPL, or a commercial license from its author). Resolve before any client-side or distributed render |
| lameenc | 1.9.0 | **LGPL-3.0-or-later** | Installed (a Demucs dependency, MP3 output) | Yes if dynamically linked and replaceable; do not use it where it is not needed |
| torch | 2.14.1+cu130 | BSD-style, several components | Installed | Yes |
| transformers | 5.21.0 | Apache-2.0 | Installed | Yes |
| huggingface-hub, safetensors, tokenizers | 2.3.0, 0.8.0, 0.23.3 | Apache-2.0 | Installed | Yes |
| numpy, scipy | 2.4.6, 1.17.1 | BSD-3-Clause and permissive bundled code | Installed | Yes |
| soundfile | 0.14.0 | BSD-3-Clause (wraps libsndfile, LGPL-2.1+) | Installed | Yes, keep libsndfile dynamically linked |
| pyloudnorm | 0.2.0 | MIT | Installed | Yes |
| julius, einops | 0.2.8, 0.8.2 | MIT | Installed | Yes |
| openvino | 2026.4.1 | Apache-2.0 | Installed | Yes (Intel NPU and iGPU drivers are separate, proprietary, free to use) |
| hnswlib | 0.8.0 | Apache-2.0 | Upstream (package metadata is blank) | Yes |
| duckdb | 2.0.0 | MIT | Installed | Yes |
| pyarrow | 26.0.0 | Apache-2.0 | Installed | Yes |
| psutil | 7.2.2 | BSD-3-Clause | Installed | Yes |
| nvidia-ml-py | 13.615.71 | BSD | Installed | Yes |
| pyyaml | 6.0.3 | MIT | Installed | Yes |
| matplotlib | 3.11.2 | Matplotlib (PSF-based, BSD-style) | Installed | Yes |
| fastapi, starlette, pydantic | 0.162.0, 1.10.0, 2.14.2 | MIT, BSD-3-Clause, MIT | Installed | Yes |
| uvicorn, httpx | 0.54.0, 0.28.1 | BSD-3-Clause | Installed | Yes |
| SQLite | bundled with Python | public domain | Upstream | Yes |

## Development and test only (not shipped)

| Package | License | Basis |
|---|---|---|
| pytest | MIT | Installed |
| hypothesis | MPL-2.0 (file-level copyleft; fine for a test dependency) | Installed |
| playwright | Apache-2.0 (drives the system Microsoft Edge here) | Installed |

## Platform software

| Item | Terms | Note |
|---|---|---|
| NVIDIA CUDA runtime and cuDNN (via the torch wheels) | NVIDIA proprietary, redistributable under their terms | Fine for self-hosted use |
| NVIDIA GeForce driver | GeForce software terms restrict data-center deployment | A commercial GPU worker needs a data-center GPU and driver, not a GeForce card, unless the terms have changed. Check the current EULA |
| Ollama | MIT | Local model runner |
| Intel NPU and Arc drivers | Intel proprietary, free | Local profile only |
| ffmpeg (gyan.dev full build) | GPL build | A tool on the owner's machine; not linked into the product |

## Data

| Data | Terms |
|---|---|
| Synthetic corpus and demo audio | Generated in this repository (`src/remixer/corpus/`); no third-party audio |
| The owner's music library | Never copied, modified or uploaded; read in place (`docs/ACCEPTANCE.md`, real-use path). Copyright stays with the rights holders |
| Playback events and ratings | Personal data once real users exist (deletion and export requirements apply) |

## Flags to resolve before a commercial launch

1. **MusicGen weights are non-commercial.** Keep them out of the commercial profile.
2. **pedalboard is GPL-3.0, and Rubber Band is GPL or paid.** Either keep rendering on servers you operate, buy a Rubber Band
   license and replace the Pedalboard dependency, or accept the GPL for anything distributed.
3. **Llama-family models have conditions.** Prefer an Apache-2.0 model for the hosted insight layer.
4. **GPU driver terms for cloud workers.**
5. **Training-data provenance** of Demucs and CLAP, if a customer asks.

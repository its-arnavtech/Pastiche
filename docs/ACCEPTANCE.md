# POC 1 acceptance (spec section 10)

Checked 2026-10-29 on branch `dev` against `docs/specs/stemdna-poc1-local-max.md` section 10. Evidence is a command, a test name or a
report; nothing here is asserted without one. Full suite at the time of writing: **426 tests collected, all passed** (`uv run pytest`,
including 28 + 14 browser tests that run on the system Microsoft Edge). Demo: `uv run remixer demo` passed **33 of 33** checks in 180 s
(`reports/demo/demo.log`, `summary.json`, `DEMO.md`).

## Verdict

| # | Criterion | Verdict |
|---|---|---|
| 1 | Process a library of at least 200 tracks end to end, resumable after a forced kill | **PASS** |
| 2 | Sustained stress run: GPU and CPU mostly above 90 %, no OOM, no data loss | **PARTIAL** |
| 3 | Remixes are reproducible: same recipe plus seed gives an identical render | **PASS** |
| 4 | The player logs every control; the heatmap detector is correct incl. undo and burst | **PASS** |
| 5 | Banning a song flags dependent recipes and re-renders only the affected sections | **PASS** |

**5 criteria: 4 pass, 1 partial, 0 fail.** Counting the sub-checks below: 11, of which 9 pass, 2 partial, 0 fail.

## 1. At least 200 tracks, resumable after a forced kill: PASS

| Sub-check | Verdict | Evidence |
|---|---|---|
| 1a. 200+ tracks processed end to end | PASS | A 500-track synthetic corpus (29.94 audio hours): generated in 639 s; all 2,500 mixes and stems analyzed with 0 errors, mean BPM error 0.276, tonic-and-mode accuracy 100 % (`docs/reports/cpu-lane.md`); separated with Demucs and re-embedded as 2,000 stems and 86,816 windows (`tasks/T-030_*.md`, changelog `20261029-143513`). The 20-track demo ran every stage in one command (below) |
| 1b. Resumable after a forced kill | PASS | `tests/test_core.py::test_queue_survives_forced_kill` (a worker killed holding a lease; a survivor leases the job). **Demo, step 3:** the real separation worker was killed with the queue at `{'done': 4, 'leased': 12, 'queued': 4}`, leaving 4 half-written stem files; the restart finished with `{'done': 20}`, 80 stems, 0 leftover partial files, 12 jobs re-leased and nothing duplicated. That kill found a real bug (finished stems never registered); fixed, covered by `tests/test_resume.py` (3 tests) |

Caveats, stated plainly:
- The 500 tracks went through the stages one command at a time over several hours, not as one streaming run. Stage overlap (spec section 6) was exercised by the benchmark, not by the demo.
- The forced kill was demonstrated on 20 tracks, not on the 500, and not at random points. The embedder's registration is still not one transaction (`docs/KNOWN_LIMITATIONS.md` item 12).
- All tracks are synthetic. No real music has been separated (`KNOWN_LIMITATIONS.md` item 10).

## 2. Sustained stress run: PARTIAL

Numbers from `reports/peak/*/summary.json` (the sustain step of each run) and `docs/PEAK_REPORT.md`.

| Run | Config | GPU util mean (samples at or above 90 %) | CPU util mean (samples at or above 90 %) | VRAM max |
|---|---|---|---|---|
| Round 1, 60 min (`20261029-001335`) | uncapped, Balanced power mode | **93.99 %** (84.6 %) | **89.05 %** (94 %) | 6.71 GiB |
| Round 2, 60 min (`20261029-123752`) | capped, pinned lanes | 93.98 % (85.1 %), but the watchdog paused the CPU and NPU lanes for the last 22 min | 53.82 % (0.1 %) | 4.39 GiB |
| Round 3, 15 min (`20261029-142810`) | **the final tuned configuration, now the stable preset** | 89.18 % (78.3 %) | 80.56 % (3.8 %) | 4.45 GiB |
| Round 5, 15 min (`20261029-150303`) | same with 10 CPU workers | 86 % (71 %) | 87 % (42 %) | 4.39 GiB |

| Sub-check | Verdict | Why |
|---|---|---|
| 2a. GPU mostly above 90 % | **PARTIAL** | Met in round 1 and (with the catch above) round 2. The shipped default sits at 89-90 % mean, with 78 % of samples at or above 90 %. The GPU is clock-limited by heat (`sw_thermal` in 88-97 % of samples) at about 55 W |
| 2b. CPU mostly above 90 % | **PARTIAL** | Met only in round 1 (94 % of samples at or above 90 %), the uncapped configuration that, run again under Best performance, powered the laptop off twice. The shipped default does not meet it (80.6 % mean) and trades CPU for GPU: 6 workers give the GPU 90.2 % and the CPU lane 75 %; 10 workers give the CPU lane 95 % and the GPU 86 % (`PEAK_REPORT.md`, "Pass condition"). Heat, not software, is the limit |
| 2c. No OOM | PASS | VRAM peaked at 7.93 GiB of 8 in the round-1 GPU ramp at batch 10. Windows spills past 8 GB into shared memory instead of raising OOM (decision 0010). No out-of-memory event was logged in any run, and the batch sizer halves on `OutOfMemoryError` (`gpu/vram.py`) |
| 2d. No data loss | PASS | Results are written after every step, so the two unexpected power-offs (System event 6008, runs `20261029-093611` and `-095035`) lost only the steps that had not run yet; the job queue, catalog and checkpoints survived (see 1b) |

What is not proven: the final tuned configuration never had its own 60-minute sustain (the 60-minute runs are rounds 1 and 2; the tuned
rounds were 15 minutes each), and the new default's 93 C CPU cutoff has had no sustained run at all (decision 0030, `KNOWN_LIMITATIONS.md` item 6). Per the wrap-up brief no further stress run was made.

Gap closed here: the default used to be the uncapped configuration. It is now the capped one, so the shipped behaviour is the one
that has been shown to survive.

## 3. Reproducible remixes: PASS

| Evidence | What it shows |
|---|---|
| `tests/cpu/test_render.py::test_seeded_assembly_and_byte_identical_rubberband` | same seed gives the same recipe, and two renders are byte-identical |
| `tests/test_patch_render.py::test_patch_touches_only_listed_sections_and_matches_full_render` | a patched render and a full render of the new version have the same sha256 |
| `tests/contracts/test_determinism.py` (3 tests) | the pipeline through the event sink, blob keys and lease order are deterministic |
| `docs/reports/cpu-lane.md` | full 30-second storm recipe reproduced exactly, compared with the sustained-run output |
| Demo, step 7 | "render is reproducible (fresh cache, identical sha256)": recipe rendered twice, once into an empty section cache, same hash |

Caveat: identical on the same machine and library versions (Rubber Band and Pedalboard are pinned in `uv.lock`). Per-stem effects are not applied by the renderer, so reproducibility holds for what the renderer does, not for the full recipe intent (`KNOWN_LIMITATIONS.md` item 1).

## 4. Player logs every control; heatmap detector correct: PASS

| Sub-check | Verdict | Evidence |
|---|---|---|
| 4a. Every section 5 control is logged | PASS | `tests/web/test_player.py` (28 browser tests, each against the mock and the real backend): play and pause with positions, seek of exactly 5 s, seek back clamped at 0, next and previous, track end, keyboard shortcuts, ratings, an event is dropped when rejected, a UI session reconstructs as burst with undo. `tests/test_player_backend.py` (5 tests): events stored in order, invalid events rejected. Demo, step 8: 72 scripted events accepted; a `seek_fwd_10s` is refused with a 400 |
| 4b. Detector correct on known patterns incl. undo and burst | PASS | `tests/analytics/test_interpret.py` (burst is one skip of N presses, quick undo cancels, overshoot-undo, replay, late return), `test_heatmap.py` (3-listen rule, single skip never a candidate, skipped-then-undone is not a candidate, denominator is listens that reached the window), `test_properties.py` (hypothesis streams keep counts consistent; planted windows recovered; precision 0.981 and recall 0.991 on the sparse 200-track set, precision 1.0 for every persona alone; `lean_back` alone has recall 0.125 because that persona skips only half the time, as designed). Demo, step 9: a 3-press burst is **one** skip of 15 s, an overshoot plus -5 s is cancelled (0 ms skipped, 5 s undone), a -5 s into heard audio is a 5 s replay, the singly-skipped 10-15 s window is a candidate, the undone and replayed ones are not (`reports/demo/heatmap.png`) |

## 5. Banning a song flags dependent recipes and re-renders only the affected sections: PASS

| Sub-check | Verdict | Evidence |
|---|---|---|
| 5a. Dependent recipes flagged | PASS | `tests/planner/test_ban.py::test_patch_is_minimal_correct_and_never_mutates`; `tests/contracts/test_planner_catalog.py` (lineage lookups on the SQLite store). Demo, step 12: the banned song was in 4 of 4 recipes and exactly 4 patches were produced; no current recipe contains it afterwards; future plans avoid it; the player now serves the patched versions |
| 5b. Only affected sections re-rendered | PASS | `tests/test_patch_render.py`. Demo, step 12: **5 of 16 sections** re-rendered across the 4 recipes (for example recipe `0cc61df3`: section 1 re-rendered, sections 0, 2, 3 cache hits with unchanged hashes and byte-identical audio). No-replacement sections are flagged `needs_regeneration` (`test_no_acceptable_replacement_marks_needs_regeneration`) |

## Beyond section 10: the real-use path and other wrap-up checks

| Check | Result | Evidence |
|---|---|---|
| A rating made in the player reaches fatigue and changes the next batch | PASS | `tests/test_real_use_path.py::test_player_rating_reaches_fatigue_and_changes_the_next_batch`: a `rate_down` on one stem posted through `PlayerBackend.append` lands in `rating_events`, makes the stem disliked in the replayed fatigue model, and the next batch with the same seed no longer contains it. Demo, step 11: rated-down stem fatigue 0.00 to 0.30 and disliked; its nearest neighbour 0.00 to 0.09; a tired-of stem 0.00 to 0.60; the next batch avoids the rated-down stem. A rating on a whole generated track is credited to its stems by loudness share and never bans (`test_generated_track_rating_spreads_over_the_audible_stems`) |
| Synthetic and real ratings never mix | PASS | `tests/test_real_use_path.py::test_synthetic_and_real_never_mix`: separate planner catalogs, fatigue and taste per origin; rating rows tagged `synthetic=0/1`; a recipe built from both origins raises `OriginMixError`; no real taste checkpoint can be borrowed from the synthetic one. Also `tests/test_taste.py::test_synthetic_and_real_never_mix`. Gap: real ratings do not yet retrain the taste model (`KNOWN_LIMITATIONS.md` item 9) |
| A library folder scanned read-only is never modified | PASS | `tests/test_real_use_path.py::test_scanned_library_is_never_modified`: files set read-only, scanned twice and analyzed in place; contents, sizes, mtimes, permissions and the set of files are identical, rows are `synthetic=0` with no blob copy. Code path: `ingest.ingest_library` hashes and reads in place; `FsBlobStore.put_file` copies, never moves. Limit: a read-only attribute test, not a filesystem-level proof for every future code path |
| Stable preset is the default; `--unleashed` warns | PASS | `tests/test_presets.py` (6 tests); decision 0030 |
| The demo uses its own data directory | PASS | demo log line "the real data/ directory is not used"; the user's `data/` was not opened by the demo |

## Gaps that were cheap to close and were closed

- The default configuration is now the capped one that survived (decision 0030), with the CPU cutoff fixed to 93 C.
- Ratings from the player had no path to fatigue and the planner; `src/remixer/product.py` provides it.
- Resume lost finished-but-unregistered stems and vectors; fixed with tests.
- Analysis gave pads and vocal lines junk tempos (136-179 BPM for a 120 BPM song); tempo and key are now song-level.

## Gaps that are not cheap (see `docs/KNOWN_LIMITATIONS.md`)

The final tuned configuration's own 60-minute sustain and the 93 C cutoff were never run; the CPU/GPU shared-cooling limit; per-stem effects
in renders; real-rating taste retraining; a real music library never run; the unscheduled nightly job and weak local LLM.

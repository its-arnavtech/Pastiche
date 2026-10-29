# remixer demo

Real Demucs + CLAP on the GPU, 20 synthetic tracks, stable preset.

| Step | Seconds |
|---|---:|
| generate 20 synthetic tracks | 15.6 |
| ingest into the catalog and enqueue separation | 0.1 |
| separate into stems (Demucs htdemucs) with one forced kill and resume | 54.1 |
| analyze stems (tempo, key, LUFS) on the CPU lane | 7.5 |
| embed stems and 5-second windows (CLAP) | 65.0 |
| train the taste model (synthetic ratings) and score every stem | 11.6 |
| plan 4 recipes and render them (section-cached) | 18.9 |
| serve them from the real player backend; replay a scripted listening session | 1.1 |
| heatmap: burst, undo, replay, candidate window | 0.9 |
| insight layer: surface an insight in the passive inbox | 0.1 |
| ratings change the next batch (fatigue); synthetic and real stay apart | 0.4 |
| ban a song: patch only the affected sections, keep every other hash | 5.1 |

## Checks

- PASS: stable preset active
- PASS: corpus generated
- PASS: ingest registered every track
- PASS: every track separated into 4 stems (80 stems, queue {'done': 20})
- PASS: kill-and-resume: killed mid-run, resumed, nothing lost or duplicated (at the kill {'done': 4, 'leased': 12, 'queued': 4}; after resume {'done': 20})
- PASS: every stem has an analysis row (80 rows)
- PASS: every stem embedded (80 stems, 480 windows)
- PASS: every stem has a finite taste score
- PASS: 4 recipes planned, every section has at least 3 of the 4 roles, and any gap has a reason (unfilled 8)
- PASS: render is reproducible (fresh cache, identical sha256) (a5b5408b669dba66)
- PASS: audio served with HTTP Range
- PASS: player lists the rendered recipes (4 generated)
- PASS: every event stored in order
- PASS: an invalid control (seek +10 s) is rejected (event 0: event_type 'seek_fwd_10s' not in ('play', 'pause', )
- PASS: a burst of 3 presses is ONE skip (one burst, three presses) (1 burst, 3 presses, 15000 ms skipped)
- PASS: overshoot then -5 s is an undo: the skip is cancelled (net skipped 0 ms, undone 5000 ms)
- PASS: a -5 s into a region just heard is a replay (5000 ms replayed)
- PASS: the singly-skipped window (10-15 s) is a candidate
- PASS: the undone skip and the replayed region are not candidates
- PASS: an insight is waiting in the passive inbox (1 item(s))
- PASS: ratings land in rating_events tagged synthetic=1
- PASS: rating -> rating_events -> fatigue: stem disliked, neighbour and tired stems fatigued
- PASS: the next recipe batch changed and avoids the rated-down stem
- PASS: no real-origin events or tracks exist in the demo
- PASS: real-origin fatigue sees none of the synthetic ratings
- PASS: a real planner cannot use the synthetic taste model
- PASS: a real-origin planner sees no synthetic stems
- PASS: ban flagged exactly the recipes that contain the song (4 patches)
- PASS: only the affected sections were re-rendered; every other section hash and its audio is unchanged (5 of 16 sections re-rendered across 4 recipes)
- PASS: recipes without the song were not touched (0 recipes)
- PASS: the banned song appears in no current recipe
- PASS: future plans avoid the banned song
- PASS: the player now serves the patched versions

---
ts: 2026-10-29T03:13:42Z
agent: cursor-opus
branch: feature/skip-analytics
type: bench
tasks: [T-014]
files: [src/remixer/analytics/simulate.py, src/remixer/analytics/scale.py, src/remixer/analytics/interpret.py, tests/analytics/test_properties.py, tests/analytics/test_scale.py, tests/analytics/conftest.py, docs/decisions/0005-skip-interpretation-defaults.md]
---

## What changed

Simulator (remixer.analytics.simulate): 4 owner personas (attentive, impatient, lean_back, shuffle_hopper) generating sessions with planted dislikes (skip bursts with reaction delay, overshoot+undo, anticipatory presses on repeat listens), teases (skipped then undone), loved regions (replays), random lone skips, early nexts, abandoned tracks, pauses, shuffle sessions and re-rendered v2 versions; every event flagged client_info.synthetic=true. Property tests (hypothesis): arbitrary event streams and player scripts keep counts consistent; a window skipped once is never flagged; skipped-then-undone is never counted or flagged; planted windows recovered for any persona mix with expected skip probability >= 0.75. Scale path (remixer.analytics.scale): Parquet (zstd) + DuckDB ordered read, hash-partitioned across spawn workers, merged heatmap written to Parquet. Interpretation: last_press_credit=0.75 (decision 0005) removed every simulator false positive. DETECTOR: 20 fixed seeds x (40 tracks, 400 sessions): precision 1.0000, recall 1.0000 (tp 1086, fp 0, fn 0); with full credit 1.0 it was precision 0.9963, recall 1.0. Per persona alone: attentive/impatient/shuffle_hopper P=1.0 R=1.0; lean_back (skips half the time, no clear majority by design) P=1.0 R=0.125. Sparse (200 tracks, 60 sessions): P=0.981 R=0.991. SCALE (4-core cloud VM, 2000 tracks, end to end from Parquet = durations query + interpret + aggregate + write heatmap Parquet): 1,000,009 events (9.3 MB) 3.93 s = 254k ev/s; 5,000,036 events (46.7 MB) 15.64 s = 320k ev/s; 10,000,036 events (93.5 MB, 2.40M listens) 30.37 s = 329k ev/s; precision/recall 1.0/1.0 at every size. Generating+writing the events is separate: 8.9 s / 43.8 s / 88.8 s.

## Why

T-014 DoD: detector correct on synthetic events with known skip patterns incl. undo and burst; scale numbers requested by the brief.

## How to verify

uv sync --all-extras; uv run pytest tests/analytics (P/R report prints at the end); uv run pytest -m scale tests/analytics/test_scale.py; PYTHONPATH=src uv run python -m remixer.analytics.scale --events 5000000

## Next / handoff

T-014 done. Detector output (WindowStats candidates) feeds remixer.fatigue.insights (T-015). The core EventSink adapter (T-001) should store the envelope from remixer.analytics.events unchanged; the scale module shows the Parquet layout.

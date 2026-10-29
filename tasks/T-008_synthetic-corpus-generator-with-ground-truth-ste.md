---
id: T-008
title: Synthetic corpus generator with ground-truth stems
status: done
owner: gpt-sol
branch: dev
lane: cpu
depends_on: [T-001]
owns_paths: [src/remixer/corpus/]
claimed_at: 2026-10-29T02:33:02Z
heartbeat_at: 2026-10-29T14:11:46Z
priority: P0
---

## Goal

Generate a synthetic library (>=200 tracks) with known drums/bass/vocals/other stems, plus pitch/tempo-augmented variants with new content hashes. Rows flagged synthetic/augmented.

## Definition of done

`remixer corpus generate --n 200` is deterministic by seed; ground-truth stems stored for SDR checks.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner gpt-sol)
- 2026-10-29T02:33:03Z gpt-sol: claimed
- 2026-10-29T02:39:03Z gpt-sol: Implementation tested; generating 500 tracks with 17 workers. Shared guard API still being built; local 10 GiB floor active.
- 2026-10-29T02:56:02Z gpt-sol: 500 tracks complete, 107768.40 audio seconds in639.16s,168.61x realtime,89.85%mean hostCPU. Test and final task commit pending.
- 2026-10-29T03:00:10Z gpt-sol: done: 500 seeded44.1kHz stereo tracks and exact stems generated;29.94h audio;639.16s wall;168.61x realtime;tests pass;manifest data/corpus/manifest.parquet.
- 2026-10-29T05:12:45Z gpt-sol: handoff: 500legacytracks/29.94h plus24versionedvariedtracks validated. Defaultgenerator8progressions/4drumstyles;--legacy-arrangementpreservesoriginalhashes. All120variedfiles analyzedzeroerrors;key91.67%,tempo0.285BPMMAE.
- 2026-10-29T14:11:46Z gpt-sol: done: Final verification: 500 legacy tracks (29.94 h) plus 24 varied-arrangement validation tracks; deterministic true stems and read-only provenance verified. Report: docs/reports/cpu-lane.md. Full suite 239 passed.

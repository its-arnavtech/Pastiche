"""CLI for the GPU lane: ingest, separate (embed, taste, musicgen register here as they land)."""
from __future__ import annotations

import json
from pathlib import Path


def cmd_ingest(args) -> None:
    from remixer.adapters import build
    from remixer.ingest import ingest_corpus, ingest_library

    a = build()
    out = {}
    if args.library:
        out["library"] = ingest_library(a, Path(args.library), enqueue=not args.no_enqueue)
    corpus = Path(args.corpus) if args.corpus else a.profile.data_dir / "corpus"
    if corpus.exists():
        out["corpus"] = ingest_corpus(a, corpus, enqueue=not args.no_enqueue)
    out["jobs"] = a.jobs.counts()
    print(json.dumps(out, indent=2))


def cmd_separate(args) -> None:
    from remixer.adapters import build
    from remixer.gpu.separate import Separator, summary
    from remixer.guards import get_guard

    a = build()
    sep = Separator(a, model=args.model, heavy=args.heavy, shifts=args.shifts, batch=args.batch,
                    feeders=args.feeders)
    guard = get_guard(a.profile.data_dir, a.profile.mode)
    if args.heavy or args.corpus_cycle:
        met = sep.run(sep.corpus_cycle(), persist=False, duration_s=args.duration, guard=guard)
    else:
        met = sep.run(sep.leased(limit=args.limit), persist=True, duration_s=args.duration, guard=guard)
        if args.loop and (not args.duration or met.t0):
            import time

            left = None if not args.duration else args.duration - (time.perf_counter() - met.t0)
            if left is None or left > 0:
                heavy = Separator(a, heavy=True, feeders=args.feeders)
                print(json.dumps(summary(met)))
                met = heavy.run(heavy.corpus_cycle(), persist=False, duration_s=left, guard=guard)
    print(json.dumps({**summary(met), "batch": sep.sizer.batch or args.batch, "jobs": a.jobs.counts()}))


def register(sub) -> None:
    p = sub.add_parser("ingest", help="register corpus/library tracks and enqueue separation")
    p.add_argument("--corpus", help="corpus dir (default <data>/corpus)")
    p.add_argument("--library", help="real music library (read-only)")
    p.add_argument("--no-enqueue", action="store_true")
    p.set_defaults(fn=cmd_ingest)

    p = sub.add_parser("separate", help="Demucs separation worker (holds the gpu lane)")
    p.add_argument("--model", help="default from profile (htdemucs; heavy: htdemucs_ft)")
    p.add_argument("--heavy", action="store_true", help="load generator: htdemucs_ft + shifts, no outputs")
    p.add_argument("--shifts", type=int)
    p.add_argument("--batch", type=int, help="fixed batch size (default: autosized from free VRAM)")
    p.add_argument("--feeders", type=int, help="decode threads (default: gpu_lane.feeder_cores)")
    p.add_argument("--limit", type=int, help="max tracks")
    p.add_argument("--duration", type=float, help="stop after N seconds")
    p.add_argument("--loop", action="store_true", help="after the queue drains, keep the GPU busy in heavy mode")
    p.add_argument("--corpus-cycle", action="store_true",
                   help="benchmark: cycle the catalog without writing stems or touching the queue")
    p.set_defaults(fn=cmd_separate)

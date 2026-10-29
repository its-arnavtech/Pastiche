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
    a.compute.prioritize_current_process("gpu")
    sep = Separator(a, model=args.model, heavy=args.heavy, shifts=args.shifts, batch=args.batch,
                    feeders=args.feeders)
    guard = get_guard(a.profile.data_dir, a.profile.mode)
    if args.heavy or args.corpus_cycle:
        met = sep.run(sep.corpus_cycle(), persist=False, duration_s=args.duration, guard=guard)
    else:
        met = sep.run(sep.leased(limit=args.limit, lease_s=args.lease_s), persist=True, duration_s=args.duration, guard=guard)
        if args.loop and (not args.duration or met.t0):
            import time

            left = None if not args.duration else args.duration - (time.perf_counter() - met.t0)
            if left is None or left > 0:
                heavy = Separator(a, heavy=True, feeders=args.feeders)
                print(json.dumps(summary(met)))
                met = heavy.run(heavy.corpus_cycle(), persist=False, duration_s=left, guard=guard)
    print(json.dumps({**summary(met), "batch": sep.sizer.batch or args.batch, "jobs": a.jobs.counts()}))


def cmd_embed(args) -> None:
    from remixer.adapters import build
    from remixer.gpu.embed import Embedder, summary
    from remixer.guards import get_guard

    a = build()
    a.compute.prioritize_current_process("gpu")
    emb = Embedder(a, model=args.model, batch=args.batch, feeders=args.feeders)
    guard = get_guard(a.profile.data_dir, a.profile.mode)
    if args.corpus_cycle:
        met = emb.run(emb.stems_cycle(), persist=False, duration_s=args.duration, guard=guard)
    else:
        n = emb.enqueue_missing()
        met = emb.run(emb.leased(limit=args.limit), persist=True, duration_s=args.duration, guard=guard)
        emb.close()
        print(json.dumps({"enqueued": n}))
    print(json.dumps({**summary(met), "batch": emb.sizer.batch or args.batch, "jobs": a.jobs.counts(f"embed:{emb.name}")}))


def cmd_taste(args) -> None:
    from dataclasses import asdict

    from remixer.adapters import build
    from remixer.gpu.taste import train

    a = build()
    a.compute.prioritize_current_process("gpu")
    res = train(a, kind="real" if args.real else "synthetic", epochs=args.epochs, duration_s=args.duration,
                batch=args.batch, width=args.width, seed=args.seed)
    print(json.dumps(asdict(res)))


def cmd_musicgen(args) -> None:
    from remixer.adapters import build
    from remixer.gpu.musicgen import run

    a = build()
    a.compute.prioritize_current_process("gpu")
    print(json.dumps(run(args.duration, args.batch, args.tokens, args.seed, adapters=a)))


def register(sub) -> None:
    p = sub.add_parser("musicgen", help="stretch: MusicGen-small inference loop as GPU load (CC-BY-NC weights)")
    p.add_argument("--duration", type=float, default=300)
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--tokens", type=int, default=256, help="new tokens per clip (50 tokens = 1 s)")
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(fn=cmd_musicgen)

    p = sub.add_parser("taste", help="train the taste MLP on window embeddings (synthetic ratings until real ones exist)")
    p.add_argument("--real", action="store_true", help="train on real ratings only (never mixed with synthetic)")
    p.add_argument("--epochs", type=int, default=50)
    p.add_argument("--duration", type=float, help="keep training for N seconds (GPU load)")
    p.add_argument("--batch", type=int, default=8192)
    p.add_argument("--width", type=int, default=256, help="first hidden layer; 256 matches the NPU scorer")
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(fn=cmd_taste)

    p = sub.add_parser("embed", help="CLAP embeddings per stem and 5-second window (holds the gpu lane)")
    p.add_argument("--model", help="default from profile (laion/clap-htsat-unfused)")
    p.add_argument("--batch", type=int, help="fixed batch of windows (default: autosized)")
    p.add_argument("--feeders", type=int)
    p.add_argument("--limit", type=int, help="max stems")
    p.add_argument("--duration", type=float, help="stop after N seconds")
    p.add_argument("--corpus-cycle", action="store_true", help="benchmark: cycle existing stems, write nothing")
    p.set_defaults(fn=cmd_embed)

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
    p.add_argument("--lease-s", type=float, default=1800, help="job lease: a killed worker's jobs return after this long")
    p.add_argument("--corpus-cycle", action="store_true",
                   help="benchmark: cycle the catalog without writing stems or touching the queue")
    p.set_defaults(fn=cmd_separate)

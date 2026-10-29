"""Evolution command registration."""
import json
from pathlib import Path

from remixer.config import data_dir


def register(sub):
    parser = sub.add_parser("synth", help="evolve software synth populations")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--generations", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.set_defaults(fn=_run)


def _run(args):
    from .lab import evolve
    print(json.dumps(evolve(args.output or data_dir() / "synth", generations=args.generations,
                            seconds=args.seconds, workers=args.workers, seed=args.seed, resume=args.resume), indent=2))

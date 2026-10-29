"""Corpus command registration for the shared CLI."""
import json
from pathlib import Path

from remixer.config import data_dir


def register(sub):
    group = sub.add_parser("corpus", help="seeded ground-truth audio corpus")
    actions = group.add_subparsers(dest="corpus_action", required=True)
    generate = actions.add_parser("generate")
    generate.add_argument("--n", type=int, default=500)
    generate.add_argument("--seed", type=int, default=0)
    generate.add_argument("--workers", type=int)
    generate.add_argument("--output", type=Path)
    generate.add_argument("--min-duration", type=float, default=120)
    generate.add_argument("--max-duration", type=float, default=300)
    generate.add_argument("--legacy-arrangement", action="store_true")
    generate.set_defaults(fn=_generate)


def _generate(args):
    from .generate import generate_corpus
    print(json.dumps(generate_corpus(args.output or data_dir() / "corpus", args.n, args.seed,
                                      args.workers, args.min_duration, args.max_duration,
                                      varied=not args.legacy_arrangement), indent=2))

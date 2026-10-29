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
    parser.add_argument("--fitness", choices=("auto", "heuristic", "taste"), default="auto")
    parser.add_argument("--taste-weights", type=Path)
    parser.add_argument("--taste-threads", type=int)
    parser.add_argument("--population", type=int)
    parser.set_defaults(fn=_run)


def _run(args):
    from .lab import HeuristicScorer, evolve
    from remixer.cpu.runtime import configured_workers
    weights = args.taste_weights or data_dir() / "models/taste/taste-mlp-v1-synthetic-w256.npz"
    use_taste = args.fitness == "taste" or args.taste_weights is not None or (args.fitness == "auto" and weights.exists())
    if use_taste:
        from .taste import ClapTasteScorer
        try:
            scorer = ClapTasteScorer(weights, threads=configured_workers(args.taste_threads or args.workers))
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            if args.fitness == "taste" or args.taste_weights is not None:
                raise
            import logging
            logging.getLogger(__name__).warning("trained checkpoint unusable (%s); retaining heuristic fitness", exc)
            use_taste = False
    if not use_taste:
        scorer = HeuristicScorer()
    output = args.output or data_dir() / ("synth-taste" if use_taste else "synth")
    print(json.dumps(evolve(output, generations=args.generations, seconds=args.seconds, workers=args.workers,
                            population_size=args.population, seed=args.seed, resume=args.resume, scorer=scorer), indent=2))

"""Analysis, recipes, rendering and CPU tuning command registration."""
import json
from pathlib import Path

from remixer.config import data_dir


def register(sub):
    analyze = sub.add_parser("analyze", help="analyze corpus mixes and stems")
    analyze.add_argument("--corpus", type=Path)
    analyze.add_argument("--output", type=Path)
    analyze.add_argument("--workers", type=int)
    analyze.add_argument("--force", action="store_true")
    analyze.add_argument("--queue", action="store_true", help="lease jobs through the durable queue")
    analyze.set_defaults(fn=_analyze)
    assemble = sub.add_parser("assemble", help="write a reproducible stem recipe")
    assemble.add_argument("--corpus", type=Path)
    assemble.add_argument("--output", type=Path, required=True)
    assemble.add_argument("--seed", type=int, default=0)
    assemble.add_argument("--duration", type=float, default=30)
    assemble.add_argument("--bpm", type=float)
    assemble.add_argument("--key")
    assemble.set_defaults(fn=_assemble)
    render = sub.add_parser("render", help="render a recipe or sustain a render storm")
    render.add_argument("--recipe", type=Path)
    render.add_argument("--corpus", type=Path)
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--seconds", type=float, default=600)
    render.add_argument("--workers", type=int)
    render.set_defaults(fn=_render)
    cpu = sub.add_parser("cpu", help="measure tuning and sustained stage performance")
    cpu.add_argument("action", choices=("tune", "sustain"))
    cpu.add_argument("--corpus", type=Path)
    cpu.add_argument("--output", type=Path, required=True)
    cpu.add_argument("--seconds", type=float)
    cpu.add_argument("--tuning", type=Path)
    cpu.add_argument("--stages", nargs="+", default=["corpus", "analysis", "render", "synth"])
    cpu.set_defaults(fn=_cpu)


def _analyze(args):
    from .analyze import analyze_corpus, drain_analysis, enqueue_analysis
    corpus, output = args.corpus or data_dir() / "corpus", args.output or data_dir() / "analysis"
    if args.queue:
        import pyarrow.parquet as pq
        from remixer.adapters import build
        adapters = build()
        enqueue_analysis(adapters.jobs, pq.read_table(corpus / "manifest.parquet").to_pylist(), output)
        print(json.dumps(drain_analysis(adapters.jobs, args.workers), indent=2))
    else:
        print(json.dumps(analyze_corpus(corpus, output, args.workers, args.force), indent=2))


def _assemble(args):
    import pyarrow.parquet as pq
    from .assemble import assemble
    from remixer.corpus.generate import atomic_json
    rows = pq.read_table((args.corpus or data_dir() / "corpus") / "manifest.parquet").to_pylist()
    recipe = assemble(rows, args.seed, args.duration, args.bpm, args.key)
    atomic_json(args.output, recipe.to_dict())
    print(recipe.identity)


def _render(args):
    from .render import render, render_storm
    from .assemble import Recipe
    if args.recipe:
        result = render(Recipe.from_dict(json.loads(args.recipe.read_text())), args.output)
    else:
        result = render_storm(args.corpus or data_dir() / "corpus", args.output, args.seconds, args.workers)
    print(json.dumps(result, indent=2))


def _cpu(args):
    from .tuner import sustain, tune
    corpus = args.corpus or data_dir() / "corpus"
    if args.action == "tune":
        result = tune(corpus, args.output, args.seconds or 15, tuple(args.stages))
    else:
        result = sustain(corpus, args.output, args.seconds or 600, args.tuning, tuple(args.stages))
    print(json.dumps(result, indent=2))

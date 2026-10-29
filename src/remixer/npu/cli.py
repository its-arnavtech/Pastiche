"""Intel scorer command registration."""
import json
from pathlib import Path

from remixer.config import data_dir


def register(sub):
    parser = sub.add_parser("npu", help="benchmark Intel NPU/iGPU and CPU fallback")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seconds", type=float, default=600)
    parser.add_argument("--devices", nargs="+", default=["NPU", "GPU.0", "CPU"])
    parser.add_argument("--parallel", action="store_true")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--weights", type=Path)
    selection.add_argument("--random-scorer", action="store_true")
    parser.set_defaults(fn=_run)


def _run(args):
    from .scorer import benchmark, resolve_spec
    print(json.dumps(benchmark(args.output or data_dir() / "npu", args.seconds, tuple(args.devices),
                               parallel=args.parallel, spec=resolve_spec(args.weights, args.random_scorer)), indent=2))

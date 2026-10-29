"""`remixer bench stress|report`."""
from __future__ import annotations

import re
from pathlib import Path


def parse_duration(s: str) -> float:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([smh]?)", s.strip())
    if not m:
        raise ValueError(f"bad duration {s!r} (use e.g. 90s, 60m, 1h)")
    return float(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600}[m.group(2)]


def cmd_stress(args) -> None:
    from remixer.bench.stress import run

    if not args.ramp and not args.sustain:
        args.ramp = True
    print(run(args))


def cmd_report(args) -> None:
    from remixer.bench.report import REPO, all_runs, summarize, write_peak_report

    if args.run:
        summarize(Path(args.run))
    elif args.all:
        for d in sorted((REPO / "reports" / "peak").glob("*/meta.json")):
            summarize(d.parent)
    print(write_peak_report(all_runs()))


def register(sub) -> None:
    b = sub.add_parser("bench", help="stress benchmark and peak report").add_subparsers(dest="bcmd", required=True)
    s = b.add_parser("stress", help="ramp lanes, find knees, sustain all lanes")
    s.add_argument("--ramp", action="store_true", help="25/50/75/100%% per lane, then all lanes together")
    s.add_argument("--sustain", type=parse_duration, help="hold the best configuration, e.g. 60m")
    s.add_argument("--step-seconds", type=parse_duration, default=90.0)
    s.add_argument("--lanes", nargs="+", default=["gpu", "cpu", "npu"], choices=["gpu", "cpu", "npu"])
    s.add_argument("--levels", nargs="+", help="sustain levels per lane, e.g. gpu=1 cpu=0.75")
    s.add_argument("--gpu-mode", default="loop", choices=["loop", "cycle", "heavy"],
                   help="sustain GPU work: queue then heavy (loop), corpus cycle, or heavy only")
    s.add_argument("--wait-locks", type=parse_duration, default=0.0, help="wait this long for held locks")
    s.add_argument("--owner", default="opus-cc")
    s.add_argument("--no-pin", action="store_true", help="OS scheduling instead of per-lane core sets (decision 0024)")
    s.add_argument("--label", default="")
    s.add_argument("--out")
    t = s.add_argument_group("load caps and thermal protection (decision 0025)")
    t.add_argument("--cool", action="store_true",
                   help="preset: cpu<=8 workers, gpu batch<=8, light Demucs only, NPU without iGPU, "
                        "pause CPU/NPU lanes at CPU zone 97 C or GPU 90 C, cool to 82 C between steps (10 s medians)")
    t.add_argument("--cpu-max-workers", type=int)
    t.add_argument("--gpu-max-batch", type=int)
    t.add_argument("--no-igpu", action="store_true", help="NPU lane never adds the Intel iGPU")
    t.add_argument("--no-heavy", action="store_true", help="GPU lane never switches to htdemucs_ft + shifts")
    t.add_argument("--cpu-limit-c", type=float, help="pause CPU/NPU lanes while the CPU zone is at or above this")
    t.add_argument("--gpu-limit-c", type=float, help="pause CPU/NPU lanes while the GPU is at or above this")
    t.add_argument("--cooldown-c", type=float, help="before each step, wait until the CPU zone is below this")
    s.set_defaults(fn=cmd_stress)
    r = b.add_parser("report", help="rebuild docs/PEAK_REPORT.md from reports/peak/*")
    r.add_argument("--run", help="re-summarize one run dir first")
    r.add_argument("--all", action="store_true", help="re-summarize every run")
    r.set_defaults(fn=cmd_report)

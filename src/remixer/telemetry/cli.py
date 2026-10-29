"""`remixer telemetry run|dashboard`."""
from __future__ import annotations

import time
from pathlib import Path


def cmd_run(args) -> None:
    from remixer.config import load_profile
    from remixer.telemetry.sampler import Sampler

    p = load_profile()
    out = Path(args.out) if args.out else p.path("telemetry") / time.strftime("%Y%m%d-%H%M%S")
    s = Sampler(out, interval_s=args.interval or p["telemetry"]["interval_s"]).start()
    print(f"telemetry -> {out}", flush=True)
    try:
        if args.duration:
            time.sleep(args.duration)
        else:
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        s.stop()


def cmd_dashboard(args) -> None:
    from remixer.config import load_profile
    from remixer.telemetry.dashboard import render
    from remixer.telemetry.sampler import load

    p = load_profile()
    run = Path(args.run) if args.run else max((d for d in p.path("telemetry").iterdir() if d.is_dir()),
                                               key=lambda d: d.stat().st_mtime)
    out = Path(args.out) if args.out else run / "dashboard.html"
    print(render(load(run), out, title=f"Telemetry {run.name}"))


def register(sub) -> None:
    t = sub.add_parser("telemetry", help="telemetry sampler and dashboard").add_subparsers(dest="tcmd", required=True)
    r = t.add_parser("run", help="sample to Parquet until stopped")
    r.add_argument("--duration", type=float)
    r.add_argument("--interval", type=float)
    r.add_argument("--out")
    r.set_defaults(fn=cmd_run)
    d = t.add_parser("dashboard", help="render a static HTML dashboard from a telemetry run")
    d.add_argument("--run", help="telemetry run dir (default: newest)")
    d.add_argument("--out")
    d.set_defaults(fn=cmd_dashboard)

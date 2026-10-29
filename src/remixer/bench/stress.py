"""`remixer bench stress`: ramp each lane, find its knee, then sustain all lanes together.

Lanes run as subprocesses of the shared CLI (each prints a JSON result), so the bench measures
exactly what the lanes ship. The telemetry sampler runs in this process and tags every sample
with the current step, so per-step utilization comes straight from the Parquet.

Ramp: each lane alone at 25/50/75/100 % of its budget, then all lanes together at the same
levels. Knee = highest level whose throughput still improved >= 3 % over the best so far
(or the last level before a failure). Sustain: all lanes at the combined knee for N minutes.
"""
from __future__ import annotations

import json
import logging
import math
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger("remixer.bench")
LEVELS = (0.25, 0.5, 0.75, 1.0)
KNEE_GAIN = 0.03


@dataclass
class Step:
    phase: str          # ramp:gpu | ramp:cpu | ramp:npu | ramp:all | sustain
    lane: str
    level: float
    config: dict
    seconds: float
    tag: str
    t_start: float = 0.0
    t_end: float = 0.0
    ok: bool = False
    throughput: float = 0.0
    unit: str = ""
    result: dict = field(default_factory=dict)
    error: str = ""


def last_json(text: str) -> dict:
    """The last top-level JSON object printed by a lane (single-line or indented)."""
    lines = text.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].startswith("{"):
            try:
                return json.loads("\n".join(lines[i:]))
            except json.JSONDecodeError:
                try:
                    return json.loads(lines[i])
                except json.JSONDecodeError:
                    continue
    raise ValueError("no JSON result in lane output")


class Lanes:
    """Command builders and result parsers for each lane. Budgets from config/resources.yaml."""

    def __init__(self, profile, out: Path, gpu_batch_max: int):
        self.p = profile
        self.out = out
        self.gpu_batch_max = gpu_batch_max
        self.cpu_max = profile.resources.cpu_workers

    def gpu(self, level: float, seconds: float, mode: str = "cycle") -> tuple[list[str], dict]:
        batch = max(1, round(level * self.gpu_batch_max))
        args = ["separate", "--batch", str(batch), "--duration", str(seconds)]
        if mode == "cycle":
            args.append("--corpus-cycle")
        elif mode == "loop":
            args.append("--loop")
        elif mode == "heavy":
            args.append("--heavy")
        return args, {"batch": batch, "mode": mode}

    def cpu(self, level: float, seconds: float) -> tuple[list[str], dict]:
        workers = max(1, round(level * self.cpu_max))
        dest = self.out / "lanes" / f"render-w{workers}-{int(time.time())}"
        return ["render", "--output", str(dest), "--seconds", str(seconds), "--workers", str(workers)], \
            {"workers": workers, "stage": "render"}

    def npu(self, level: float, seconds: float) -> tuple[list[str], dict]:
        devices = ["NPU"] if level < 0.75 else ["NPU", "GPU.0"]
        dest = self.out / "lanes" / f"npu-{'-'.join(d.replace('.', '') for d in devices)}-{int(time.time())}"
        return ["npu", "--output", str(dest), "--seconds", str(seconds), "--devices", *devices, "--parallel"], \
            {"devices": devices}

    @staticmethod
    def parse(lane: str, res: dict) -> tuple[float, str]:
        if lane == "gpu":
            return float(res.get("steady_rate_x") or res.get("rate_x") or 0), "audio-s/s"
        if lane == "cpu":
            return float(res.get("audio_seconds_per_second", 0)), "rendered audio-s/s"
        if lane == "npu":
            return float(sum(r.get("inferences_per_second", 0) for r in res.get("results", []))), "inferences/s"
        raise ValueError(lane)


def run_lanes(specs: list[tuple[str, list[str], dict]], seconds: float, log_dir: Path, grace_s: float = 900):
    """Start every lane, wait for all; return {lane: (ok, result, error)}."""
    log_dir.mkdir(parents=True, exist_ok=True)
    procs = {}
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "HF_HUB_DISABLE_SYMLINKS_WARNING": "1"}
    for lane, args, _ in specs:
        f = open(log_dir / f"{lane}-{int(time.time())}.log", "w", encoding="utf-8")
        p = subprocess.Popen([sys.executable, "-m", "remixer.cli", *args], stdout=f, stderr=subprocess.STDOUT,
                             env=env, cwd=Path(__file__).resolve().parents[3])
        procs[lane] = (p, f)
    out = {}
    deadline = time.time() + seconds + grace_s
    for lane, (p, f) in procs.items():
        try:
            p.wait(timeout=max(1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        f.close()
        text = Path(f.name).read_text(encoding="utf-8", errors="replace")
        try:
            out[lane] = (p.returncode == 0, last_json(text), "" if p.returncode == 0 else text[-2000:])
        except ValueError:
            out[lane] = (False, {}, text[-2000:])
    return out


def knee(steps: list[Step]) -> Step | None:
    best = None
    for s in sorted(steps, key=lambda s: s.level):
        if not s.ok:
            break
        if best is None or s.throughput >= best.throughput * (1 + KNEE_GAIN):
            best = s
    return best


class Bench:
    def __init__(self, adapters, out: Path, step_seconds: float, lanes: tuple[str, ...], owner: str = "opus-cc"):
        self.a = adapters
        self.out = out
        self.step_seconds = step_seconds
        self.lane_names = lanes
        self.owner = owner
        self.steps: list[Step] = []
        out.mkdir(parents=True, exist_ok=True)
        from remixer.telemetry.sampler import Sampler

        self.sampler = Sampler(out / "telemetry", interval_s=adapters.profile["telemetry"]["interval_s"])
        self.lanes = Lanes(adapters.profile, out, self._gpu_batch_max())

    def _gpu_batch_max(self) -> int:
        try:
            state = json.loads((self.a.profile.data_dir / "state" / "gpu_sizes.json").read_text())
            return max(int(v["batch"]) for k, v in state.items() if "shifts=1" in k and "htdemucs@" in k)
        except (FileNotFoundError, ValueError, KeyError, json.JSONDecodeError):
            return 10

    def save(self) -> None:
        tmp = self.out / "steps.json.tmp"
        tmp.write_text(json.dumps([asdict(s) for s in self.steps], indent=2))
        os.replace(tmp, self.out / "steps.json")

    def step(self, phase: str, lanes: list[str], level: float, seconds: float,
             builders: dict[str, Callable] | None = None) -> list[Step]:
        builders = builders or {}
        specs, steps = [], []
        tag = f"{phase}@{int(level * 100)}"
        for lane in lanes:
            args, cfg = (builders.get(lane) or getattr(self.lanes, lane))(level, seconds)
            specs.append((lane, args, cfg))
            steps.append(Step(phase=phase, lane=lane, level=level, config=cfg, seconds=seconds, tag=tag))
        log.info("step %s: %s", tag, {s.lane: s.config for s in steps})
        self.sampler.tag = tag
        t0 = time.time()
        results = run_lanes(specs, seconds, self.out / "logs")
        t1 = time.time()
        self.sampler.tag = ""
        for s in steps:
            ok, res, err = results[s.lane]
            s.t_start, s.t_end, s.ok, s.result, s.error = t0, t1, ok, res, err
            if ok:
                s.throughput, s.unit = Lanes.parse(s.lane, res)
            log.info("  %s: ok=%s %.2f %s", s.lane, ok, s.throughput, s.unit)
        self.steps.extend(steps)
        self.save()
        return steps

    def ramp(self) -> dict:
        knees = {}
        for lane in self.lane_names:
            levels = LEVELS if lane != "npu" else (0.5, 1.0)
            for lv in levels:
                (s,) = self.step(f"ramp:{lane}", [lane], lv, self.step_seconds)
                if not s.ok:
                    break
            k = knee([s for s in self.steps if s.phase == f"ramp:{lane}"])
            knees[lane] = {"level": k.level, "config": k.config, "throughput": k.throughput, "unit": k.unit} if k else None
        iso = {lane: (k or {}).get("throughput") or 1.0 for lane, k in knees.items()}
        combined = []
        if len(self.lane_names) > 1:
            for lv in LEVELS:
                steps = self.step("ramp:all", list(self.lane_names), lv, self.step_seconds)
                score = sum(s.throughput / iso[s.lane] for s in steps) / len(steps)
                combined.append({"level": lv, "score": score, "ok": all(s.ok for s in steps),
                                 "lanes": {s.lane: s.throughput for s in steps}})
        best = None
        for c in combined:
            if not c["ok"]:
                break
            if best is None or c["score"] >= best["score"] * (1 + KNEE_GAIN):
                best = c
        return {"isolated_knees": knees, "combined": combined, "combined_knee": best}

    def sustain(self, seconds: float, levels: dict[str, float], gpu_mode: str = "loop") -> list[Step]:
        builders = {"gpu": lambda lv, s: self.lanes.gpu(lv, s, mode=gpu_mode)}
        lanes = list(self.lane_names)
        # One step, but each lane at its own level: run via per-lane builders bound to their level.
        bound = {ln: (lambda b, lv: (lambda _lv, s: b(lv, s)))(builders.get(ln) or getattr(self.lanes, ln), levels[ln])
                 for ln in lanes}
        return self.step("sustain", lanes, 1.0, seconds, builders=bound)


# ------------------------------------------------------------------ locks

def _agentctl():
    import importlib.util

    path = Path(__file__).resolve().parents[3] / "scripts" / "agentctl.py"
    spec = importlib.util.spec_from_file_location("agentctl", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def acquire_locks(lanes: tuple[str, ...], owner: str, ttl_min: int, note: str, wait_s: float) -> tuple[str, ...]:
    """Acquire gpu, cpu, npu in that order. Lanes still held by someone else after wait_s are dropped."""
    ac = _agentctl()
    got = []
    deadline = time.time() + wait_s
    for lane in ("gpu", "cpu", "npu"):
        if lane not in lanes:
            continue
        while True:
            held = ac.read_lock(lane)
            if not held or held.get("owner") == owner:
                ns = type("A", (), {"lane": lane, "owner": owner, "ttl": ttl_min, "note": note})
                ac.cmd_lock_acquire(ns)
                got.append(lane)
                break
            if time.time() > deadline:
                log.warning("%s lock held by %s (%s): lane skipped", lane, held["owner"], held.get("note"))
                break
            time.sleep(30)
    return tuple(got)


def release_locks(lanes, owner: str) -> None:
    ac = _agentctl()
    for lane in lanes:
        ac.cmd_lock_release(type("A", (), {"lane": lane, "owner": owner, "force": False}))


# ------------------------------------------------------------------ entry

def run(args) -> Path:
    from remixer.adapters import build
    from remixer.bench.report import write_report

    a = build()
    ts = time.strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else Path(__file__).resolve().parents[3] / "reports" / "peak" / ts
    lanes = tuple(args.lanes)
    total_min = math.ceil((args.step_seconds * 20 + (args.sustain or 0)) / 60) + 30
    got = acquire_locks(lanes, args.owner, total_min, f"bench stress {ts}", args.wait_locks)
    if not got:
        raise SystemExit("no lane locks available")
    b = Bench(a, out, args.step_seconds, got, owner=args.owner)
    meta = {"ts": ts, "lanes": got, "requested_lanes": lanes, "step_seconds": args.step_seconds,
            "sustain_s": args.sustain, "mode": a.profile.mode, "power_plan": power_plan(),
            "resources": {"logical": a.profile.resources.logical_cores, "cpu_workers": a.profile.resources.cpu_workers,
                          "gpu_feeders": a.profile.resources.gpu_feeders, "reserve": a.profile.resources.reserve},
            "gpu_batch_max": b.lanes.gpu_batch_max, "label": args.label}
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    b.sampler.start()
    ramp = None
    try:
        if args.ramp:
            ramp = b.ramp()
            (out / "ramp.json").write_text(json.dumps(ramp, indent=2))
        if args.sustain:
            levels = {ln: 1.0 for ln in got}
            if args.levels:
                levels.update({k: float(v) for k, v in (x.split("=") for x in args.levels)})
            elif ramp and ramp.get("combined_knee"):
                levels = {ln: ramp["combined_knee"]["level"] for ln in got}
            if ramp and "gpu" in levels:
                gk = (ramp["isolated_knees"] or {}).get("gpu")
                if gk:
                    levels["gpu"] = max(levels["gpu"], gk["level"])  # GPU batch never hurts other lanes
            meta["sustain_levels"] = levels
            (out / "meta.json").write_text(json.dumps(meta, indent=2))
            b.sustain(args.sustain, levels, gpu_mode=args.gpu_mode)
    finally:
        b.sampler.stop()
        release_locks(got, args.owner)
    return write_report(out)


def power_plan() -> str:
    if sys.platform != "win32":
        return "n/a"
    try:
        return subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except Exception:
        return "unknown"

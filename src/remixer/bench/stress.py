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

from remixer.adapters.local_compute import AFFINITY_ENV

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


@dataclass
class Limits:
    """Load caps and thermal protection (decision 0025). Zero = no cap / off."""
    cpu_workers: int = 0
    gpu_batch: int = 0
    igpu: bool = True
    heavy_gpu: bool = True
    cpu_limit_c: float = 0.0     # CPU package zone (ACPI _TZ.THRM)
    gpu_limit_c: float = 0.0
    resume_margin_c: float = 8.0
    cooldown_c: float = 0.0      # wait for the CPU zone to fall below this before each step
    cooldown_max_s: float = 300.0


def read_temps() -> dict:
    """CPU package zone and GPU core temperature, best effort."""
    out = {}
    try:
        from remixer.telemetry.win_engines import EngineSampler

        if not hasattr(read_temps, "eng"):
            read_temps.eng = EngineSampler()
            read_temps.eng.sample()
            time.sleep(0.2)
        out["cpu_c"] = read_temps.eng.sample().get("tz_thrm_c")
    except Exception:
        pass
    try:
        import pynvml

        pynvml.nvmlInit()
        out["gpu_c"] = pynvml.nvmlDeviceGetTemperature(pynvml.nvmlDeviceGetHandleByIndex(0),
                                                        pynvml.NVML_TEMPERATURE_GPU)
    except Exception:
        pass
    return out


class ThermalWatch:
    """Suspends the CPU and NPU lane process trees while the CPU zone or the GPU is over its limit.

    The GPU lane keeps running (its firmware throttles it); the CPU-side lanes are what tipped this
    chassis into unexpected shutdowns (decision 0025). Every pause and resume is recorded.
    """

    def __init__(self, limits: Limits, procs: dict, events: list):
        import threading

        self.l, self.procs, self.events = limits, procs, events
        self.paused = False
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _tree(self, lanes):
        import psutil

        out = []
        for lane in lanes:
            p = self.procs.get(lane)
            if p is None or p.poll() is not None:
                continue
            try:
                root = psutil.Process(p.pid)
                out += [root, *root.children(recursive=True)]
            except psutil.Error:
                pass
        return out

    def _set(self, pause: bool, why: dict) -> None:
        import psutil

        for q in self._tree(("cpu", "npu")):
            try:
                q.suspend() if pause else q.resume()
            except psutil.Error:
                pass
        self.paused = pause
        e = {"t": time.time(), "action": "pause cpu+npu lanes" if pause else "resume", **why}
        self.events.append(e)
        log.warning("thermal watch: %s", e)

    def _over(self, c, g) -> bool:
        return bool((self.l.cpu_limit_c and c is not None and c >= self.l.cpu_limit_c) or
                    (self.l.gpu_limit_c and g is not None and g >= self.l.gpu_limit_c))

    def _cool(self, c, g) -> bool:
        m = self.l.resume_margin_c
        return ((c is None or not self.l.cpu_limit_c or c < self.l.cpu_limit_c - m) and
                (g is None or not self.l.gpu_limit_c or g < self.l.gpu_limit_c - m))

    def _run(self) -> None:
        import statistics
        from collections import deque

        # The ACPI zone spikes by 15-20 C on single boosts even at idle: act on a 10 s rolling median.
        cpu, gpu = deque(maxlen=5), deque(maxlen=5)
        while not self._stop.wait(2.0):
            t = read_temps()
            if t.get("cpu_c") is not None:
                cpu.append(t["cpu_c"])
            if t.get("gpu_c") is not None:
                gpu.append(t["gpu_c"])
            if len(cpu) < cpu.maxlen and len(gpu) < gpu.maxlen:
                continue
            c = statistics.median(cpu) if cpu else None
            g = statistics.median(gpu) if gpu else None
            if not self.paused and self._over(c, g):
                self._set(True, {"cpu_c": c, "gpu_c": g})
            elif self.paused and self._cool(c, g):
                self._set(False, {"cpu_c": c, "gpu_c": g})

    def __enter__(self):
        if self.l.cpu_limit_c or self.l.gpu_limit_c:
            self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._t.is_alive():
            self._t.join(timeout=5)
        if self.paused:
            self._set(False, {"reason": "step ended"})


def cooldown(limits: Limits) -> float:
    """Block until the CPU zone is below limits.cooldown_c (or the timeout). Returns seconds waited."""
    if not limits.cooldown_c:
        return 0.0
    import statistics

    t0 = time.time()
    while time.time() - t0 < limits.cooldown_max_s:
        vals = []
        for _ in range(5):
            if (c := read_temps().get("cpu_c")) is not None:
                vals.append(c)
            time.sleep(1)
        if not vals or statistics.median(vals) < limits.cooldown_c:
            break
    return round(time.time() - t0, 1)


class Lanes:
    """Command builders and result parsers for each lane. Budgets from config/resources.yaml."""

    def __init__(self, profile, out: Path, gpu_batch_max: int, plan: dict[str, list[int]] | None = None,
                 limits: Limits | None = None):
        self.p = profile
        self.out = out
        self.limits = limits or Limits()
        self.gpu_batch_max = min(gpu_batch_max, self.limits.gpu_batch or gpu_batch_max)
        self.plan = plan or {}  # lane -> pinned logical CPUs (decision 0024); {} = OS scheduling
        self.cpu_max = profile.resources.cpu_workers
        # The CPU lane owns this measured recommendation; resource budgets still
        # cap it, and absent/incomplete tuning leaves the configured ramp intact.
        try:
            tuning = json.loads((Path(profile.data_dir) / "cpu-peak/tuning/tuning.json").read_text(encoding="utf-8"))
            self.cpu_max = min(self.cpu_max, max(1, int(tuning["best"]["render"]["workers"])))
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if self.plan.get("cpu"):
            self.cpu_max = len(self.plan["cpu"])  # one render worker per CPU-lane logical CPU at 100 %
        if self.limits.cpu_workers:
            self.cpu_max = min(self.cpu_max, self.limits.cpu_workers)

    def _pin(self, lane: str, cfg: dict) -> dict:
        if self.plan.get(lane):
            cfg["cores"] = self.plan[lane]
        return cfg

    def gpu(self, level: float, seconds: float, mode: str = "cycle") -> tuple[list[str], dict]:
        batch = max(1, round(level * self.gpu_batch_max))
        args = ["separate", "--batch", str(batch), "--duration", str(seconds)]
        if mode != "cycle" and not self.limits.heavy_gpu:
            mode = "cycle"  # heavy htdemucs_ft draws the most power; disabled under thermal limits
        if mode == "cycle":
            args.append("--corpus-cycle")
        elif mode == "loop":
            args.append("--loop")
        elif mode == "heavy":
            args.append("--heavy")
        return args, self._pin("gpu", {"batch": batch, "mode": mode})

    def cpu(self, level: float, seconds: float) -> tuple[list[str], dict]:
        workers = max(1, round(level * self.cpu_max))
        dest = self.out / "lanes" / f"render-w{workers}-{int(time.time())}"
        return ["render", "--output", str(dest), "--seconds", str(seconds), "--workers", str(workers)], \
            self._pin("cpu", {"workers": workers, "stage": "render"})

    def npu(self, level: float, seconds: float) -> tuple[list[str], dict]:
        devices = ["NPU"] if level < 0.75 or not self.limits.igpu else ["NPU", "GPU.0"]
        dest = self.out / "lanes" / f"npu-{'-'.join(d.replace('.', '') for d in devices)}-{int(time.time())}"
        return ["npu", "--output", str(dest), "--seconds", str(seconds), "--devices", *devices, "--parallel"], \
            self._pin("npu", {"devices": devices})

    @staticmethod
    def parse(lane: str, res: dict) -> tuple[float, str]:
        if lane == "gpu":
            if res.get("stage") == "separate_heavy":
                # htdemucs_ft x shifts runs 8 model passes per audio second; report per-pass throughput so
                # heavy and light steps share one unit (light htdemucs is one pass per audio second).
                return float(res.get("model_rate_x") or 0), "model-pass audio-s/s"
            return float(res.get("steady_rate_x") or res.get("rate_x") or 0), "audio-s/s"
        if lane == "cpu":
            return float(res.get("audio_seconds_per_second", 0)), "rendered audio-s/s"
        if lane == "npu":
            return float(sum(r.get("inferences_per_second", 0) for r in res.get("results", []))), "inferences/s"
        raise ValueError(lane)


def run_lanes(specs: list[tuple[str, list[str], dict]], seconds: float, log_dir: Path, grace_s: float = 900,
              limits: Limits | None = None, events: list | None = None):
    """Start every lane, wait for all under the thermal watch; return {lane: (ok, result, error)}."""
    log_dir.mkdir(parents=True, exist_ok=True)
    procs = {}
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "HF_HUB_DISABLE_SYMLINKS_WARNING": "1"}
    for lane, args, cfg in specs:
        f = open(log_dir / f"{lane}-{int(time.time())}.log", "w", encoding="utf-8")
        lane_env = dict(env)
        lane_env.pop(AFFINITY_ENV, None)
        if cfg.get("cores"):
            lane_env[AFFINITY_ENV] = ",".join(map(str, cfg["cores"]))
        p = subprocess.Popen([sys.executable, "-m", "remixer.cli", *args], stdout=f, stderr=subprocess.STDOUT,
                             env=lane_env, cwd=Path(__file__).resolve().parents[3])
        procs[lane] = (p, f)
    out = {}
    deadline = time.time() + seconds + grace_s
    with ThermalWatch(limits or Limits(), {ln: p for ln, (p, _) in procs.items()}, events if events is not None else []):
        for p, _ in procs.values():
            try:
                p.wait(timeout=max(1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                pass
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
    def __init__(self, adapters, out: Path, step_seconds: float, lanes: tuple[str, ...], owner: str = "opus-cc",
                 pin: bool = True, limits: Limits | None = None):
        self.a = adapters
        self.out = out
        self.step_seconds = step_seconds
        self.lane_names = lanes
        self.owner = owner
        self.steps: list[Step] = []
        out.mkdir(parents=True, exist_ok=True)
        from remixer.telemetry.sampler import Sampler

        self.sampler = Sampler(out / "telemetry", interval_s=adapters.profile["telemetry"]["interval_s"])
        self.limits = limits or Limits()
        self.thermal_events: list[dict] = []
        self.lanes = Lanes(adapters.profile, out, self._gpu_batch_max(), adapters.compute.core_plan() if pin else {},
                           self.limits)

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
        try:  # steps can outlast the initial TTL estimate: refresh our locks every step
            acquire_locks(tuple(self.lane_names), self.owner, int(seconds // 60) + 45, f"bench {tag}", 0)
        except SystemExit as e:
            log.warning("lock refresh failed: %s", e)
        waited = cooldown(self.limits)
        if waited:
            log.info("cooldown %.0fs before %s (CPU zone %s C)", waited, tag, read_temps().get("cpu_c"))
        self.sampler.tag = tag
        t0 = time.time()
        n_events = len(self.thermal_events)
        results = run_lanes(specs, seconds, self.out / "logs", limits=self.limits, events=self.thermal_events)
        t1 = time.time()
        self.sampler.tag = ""
        for s in steps:
            ok, res, err = results[s.lane]
            s.t_start, s.t_end, s.ok, s.result, s.error = t0, t1, ok, res, err
            s.config["thermal_events"] = self.thermal_events[n_events:]
            s.config["cooldown_s"] = waited
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

def limits_from_args(args) -> Limits:
    g = lambda name, default=None: getattr(args, name, default)  # noqa: E731
    lim = Limits(cpu_workers=8, gpu_batch=8, igpu=False, heavy_gpu=False, cpu_limit_c=97.0, gpu_limit_c=90.0,
                 cooldown_c=82.0) if g("cool") else Limits()
    if g("cpu_max_workers"):
        lim.cpu_workers = args.cpu_max_workers
    if g("gpu_max_batch"):
        lim.gpu_batch = args.gpu_max_batch
    if g("no_igpu"):
        lim.igpu = False
    if g("no_heavy"):
        lim.heavy_gpu = False
    for name in ("cpu_limit_c", "gpu_limit_c", "cooldown_c"):
        if g(name) is not None:
            setattr(lim, name, getattr(args, name))
    return lim


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
    b = Bench(a, out, args.step_seconds, got, owner=args.owner, pin=not getattr(args, "no_pin", False),
              limits=limits_from_args(args))
    meta = {"ts": ts, "lanes": got, "requested_lanes": lanes, "step_seconds": args.step_seconds,
            "sustain_s": args.sustain, "mode": a.profile.mode, "power_plan": power_plan(),
            "resources": {"logical": a.profile.resources.logical_cores, "cpu_workers": a.profile.resources.cpu_workers,
                          "gpu_feeders": a.profile.resources.gpu_feeders, "reserve": a.profile.resources.reserve},
            "gpu_batch_max": b.lanes.gpu_batch_max, "label": args.label, "core_plan": b.lanes.plan,
            "limits": asdict(b.limits)}
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


POWER_OVERLAYS = {"961cc777-2547-4f9d-8174-7d86181b8a7a": "best power efficiency",
                  "3af9b8d9-7c97-431d-ad78-34a8bfea439f": "better performance",
                  "ded574b5-45a0-4f42-8737-46345c09c238": "best performance"}


def power_plan() -> str:
    if sys.platform != "win32":
        return "n/a"
    try:
        scheme = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True,
                                timeout=10).stdout.strip()
    except Exception:
        scheme = "unknown"
    try:  # the Settings power-mode slider is an overlay on the scheme; read it, never write it
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes") as k:
            ac = winreg.QueryValueEx(k, "ActiveOverlayAcPowerScheme")[0]
        scheme += f"; AC power mode overlay: {POWER_OVERLAYS.get(ac.lower(), ac or 'balanced (none)')}"
    except OSError:
        pass
    return scheme

"""Peak report: per-run artifacts in reports/peak/<ts>/ and the cumulative docs/PEAK_REPORT.md."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
THROTTLE_KEYS = ("hw_thermal", "sw_thermal", "sw_power_cap", "hw_slowdown", "hw_power_brake")


def _col(t, name):
    if name not in t.column_names:
        return None
    v = np.array([np.nan if x is None else float(x) for x in t.column(name).to_pylist()], dtype=float)
    return v if np.isfinite(v).any() else None


def _agg(v, how):
    if v is None:
        return None
    v = v[np.isfinite(v)]
    if not len(v):
        return None
    return round(float({"mean": np.mean, "max": np.max, "min": np.min, "p95": lambda x: np.percentile(x, 95),
                        "p50": np.median, "p05": lambda x: np.percentile(x, 5)}[how](v)), 2)


def window_stats(t, mask, plan: dict | None = None) -> dict:
    sub = t.filter(mask) if mask is not None else t
    if sub.num_rows == 0:
        return {"samples": 0}
    out = {"samples": sub.num_rows}
    for lane, cores in (plan or {}).items():  # utilization of each lane's own pinned CPUs
        cols = [_col(sub, f"cpu_{c:02d}") for c in cores]
        cols = [c for c in cols if c is not None]
        if cols:
            out[f"{lane}_cores_util_mean"] = _agg(np.nanmean(np.vstack(cols), axis=0), "mean")
    for name, hows in {"gpu_util": ("mean", "p50", "p05"), "cpu_util": ("mean", "p50", "p05"),
                       "igpu": ("mean", "max"), "npu": ("mean", "max"), "vram_used_gib": ("max",),
                       "ram_used_gib": ("max",), "swap_used_gib": ("max",), "gpu_temp_c": ("mean", "max"),
                       "gpu_power_w": ("mean", "max"), "gpu_sm_mhz": ("mean", "min", "max"),
                       "cpu_mhz": ("mean", "min"), "cpu_mhz_eff": ("mean", "min", "max"), "cpu_temp_c": ("mean", "max"),
                       "disk_read_mbs": ("mean", "max"), "disk_write_mbs": ("mean", "max")}.items():
        v = _col(sub, name)
        for h in hows:
            out[f"{name}_{h}"] = _agg(v, h)
    gu, cu = _col(sub, "gpu_util"), _col(sub, "cpu_util")
    if gu is not None:
        g = gu[np.isfinite(gu)]
        out["gpu_util_frac_ge90"] = round(float((g >= 90).mean()), 3) if len(g) else None
    if cu is not None:
        out["cpu_util_frac_ge90"] = round(float((cu >= 90).mean()), 3)
    if "gpu_throttle_names" in sub.column_names:
        names = [x or "" for x in sub.column("gpu_throttle_names").to_pylist()]
        n = max(1, sum(1 for x in sub.column("gpu_throttle_names").to_pylist() if x is not None))
        for k in THROTTLE_KEYS:
            out[f"throttle_{k}_frac"] = round(sum(k in x for x in names) / n, 3)
    return out


def charts(t, steps, out: Path) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    files = []
    ts = _col(t, "ts")
    if ts is None:
        return files
    m = (ts - ts[0]) / 60
    spans = sorted({(s["t_start"], s["t_end"], s["tag"]) for s in steps})

    def mark(ax):
        for a, b, tag in spans:
            ax.axvspan((a - ts[0]) / 60, (b - ts[0]) / 60, alpha=0.06, color="gray")
            ax.text((a - ts[0]) / 60, ax.get_ylim()[1] * 0.97, tag, fontsize=6, rotation=90, va="top", color="gray")

    panels = [
        ("utilization.png", "Utilization (%)", [("gpu_util", "RTX 4060"), ("cpu_util", "CPU avg"), ("igpu", "Intel iGPU"),
                                                 ("npu", "NPU")]),
        ("gpu_thermals.png", "GPU temp (C) / power (W) / SM clock (100 MHz)",
         [("gpu_temp_c", "temp C"), ("gpu_power_w", "power W"), ("gpu_sm_100mhz", "SM clock x100 MHz")]),
        ("memory.png", "Memory (GiB)", [("vram_used_gib", "VRAM"), ("ram_used_gib", "RAM"), ("swap_used_gib", "swap")]),
        ("disk.png", "Disk (MB/s)", [("disk_read_mbs", "read"), ("disk_write_mbs", "write")]),
        ("cpu_clock.png", "CPU clock (MHz)", [("cpu_mhz", "reported CPU MHz"), ("cpu_mhz_eff", "effective CPU MHz")]),
    ]
    extra = {"gpu_sm_100mhz": (_col(t, "gpu_sm_mhz") / 100) if _col(t, "gpu_sm_mhz") is not None else None}
    for fname, title, series in panels:
        fig, ax = plt.subplots(figsize=(11, 3.2), dpi=110)
        drew = False
        for name, label in series:
            v = extra.get(name) if name in extra else _col(t, name)
            if v is None:
                continue
            ax.plot(m, v, lw=0.8, label=label)
            drew = True
        if not drew:
            plt.close(fig)
            continue
        ax.set_title(title, fontsize=9)
        ax.set_xlabel("minutes", fontsize=8)
        ax.tick_params(labelsize=7)
        ax.legend(fontsize=7, loc="lower right")
        ax.grid(alpha=0.3)
        mark(ax)
        fig.tight_layout()
        fig.savefig(out / fname)
        plt.close(fig)
        files.append(fname)
    return files


def starvation(t0: float, t1: float) -> list[dict]:
    """gpu_starvation events (GPU < 80 % with an empty feeder queue) logged by the GPU lane in [t0, t1]."""
    from remixer.adapters import build

    try:
        rows = build().events.read("gpu_starvation")
    except Exception:
        return []
    return [r for r in rows if t0 <= float(r.get("ts", 0)) <= t1]


def passes(tel: dict) -> bool | None:
    """Brief's pass condition: GPU > 90 % while the CPU lane's own cores stay near saturation (>= 90 %)."""
    g, c = tel.get("gpu_util_mean"), tel.get("cpu_cores_util_mean")
    if g is None or c is None:
        return None
    return g > 90 and c >= 90


def summarize(run: Path) -> dict:
    from remixer.telemetry.sampler import load

    meta = json.loads((run / "meta.json").read_text())
    steps = json.loads((run / "steps.json").read_text()) if (run / "steps.json").exists() else []
    ramp = json.loads((run / "ramp.json").read_text()) if (run / "ramp.json").exists() else None
    t = load(run / "telemetry")
    import pyarrow.compute as pc

    for s in steps:
        if t.num_rows:
            # lanes start (model load, compile) before their timed `seconds`; measure the timed tail only
            lo = max(s["t_start"], s["t_end"] - s["seconds"]) + min(10, s["seconds"] * 0.1)
            mask = pc.and_(pc.greater_equal(t["ts"], lo), pc.less_equal(t["ts"], s["t_end"] - 1))
            s["telemetry"] = window_stats(t, mask, meta.get("core_plan"))
            if s["lane"] == "gpu":
                s["telemetry"]["starvation_events"] = len(starvation(lo, s["t_end"]))
    overall = window_stats(t, None, meta.get("core_plan")) if t.num_rows else {}
    guard = []
    gfile = REPO / "data" / "state" / "guard_interventions.jsonl"
    if gfile.exists() and steps:
        t0, t1 = min(s["t_start"] for s in steps), max(s["t_end"] for s in steps)
        for line in gfile.read_text().splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if t0 <= e["t"] <= t1:
                guard.append(e)
    summary = {"meta": meta, "steps": steps, "ramp": ramp, "overall": overall, "guard_interventions": guard,
               "charts": charts(t, steps, run) if t.num_rows else []}
    (run / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    if t.num_rows:
        from remixer.telemetry.dashboard import render

        render(t, run / "dashboard.html", title=f"Peak run {meta['ts']}")
    return summary


def _fmt(x, nd=1):
    return "-" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def _cfg(c: dict) -> str:
    return ", ".join(f"{k}={'+'.join(v) if isinstance(v, list) else v}" for k, v in c.items())


def all_runs() -> list[dict]:
    runs = []
    for d in sorted((REPO / "reports" / "peak").glob("*/summary.json")):
        try:
            runs.append(json.loads(d.read_text()))
        except json.JSONDecodeError:
            continue
    return runs


def sustain_score(run: dict, ref: dict[str, float]) -> float | None:
    st = [s for s in run["steps"] if s["phase"] == "sustain" and s["ok"]]
    if not st:
        return None
    vals = [s["throughput"] / ref[s["lane"]] for s in st if ref.get(s["lane"])]
    return sum(vals) / len(vals) if vals else None


def verdict(run: dict) -> list[str]:
    o = run["overall"]
    sus = [s for s in run["steps"] if s["phase"] == "sustain"]
    tel = sus[0].get("telemetry", {}) if sus else o
    lines = []
    g = tel.get("gpu_util_mean")
    if g is not None:
        lines.append(f"RTX 4060: {g:.0f}% mean utilization ({100 * (tel.get('gpu_util_frac_ge90') or 0):.0f}% of samples at "
                     f">= 90%), {tel.get('gpu_temp_c_mean')} C mean / {tel.get('gpu_temp_c_max')} C max, "
                     f"{tel.get('gpu_power_w_mean')} W mean, SM clock {tel.get('gpu_sm_mhz_mean')} MHz mean "
                     f"(min {tel.get('gpu_sm_mhz_min')}). VRAM peak {tel.get('vram_used_gib_max')} GiB of 8.")
        th = {k: tel.get(f"throttle_{k}_frac") for k in THROTTLE_KEYS if tel.get(f"throttle_{k}_frac")}
        if th:
            lines.append("GPU clock-limit reasons (fraction of samples): " +
                         ", ".join(f"{k} {100 * v:.0f}%" for k, v in th.items()) + ".")
    c = tel.get("cpu_util_mean")
    if c is not None:
        lines.append(f"CPU (22 logical): {c:.0f}% mean ({100 * (tel.get('cpu_util_frac_ge90') or 0):.0f}% of samples at "
                     f">= 90%), effective clock {tel.get('cpu_mhz_eff_mean') or 'not recorded'} MHz mean "
                     f"(min {tel.get('cpu_mhz_eff_min')}; psutil reports only the {tel.get('cpu_mhz_mean')} MHz base). CPU temperature: "
                     f"{'not available (no LibreHardwareMonitor)' if tel.get('cpu_temp_c_max') is None else str(tel.get('cpu_temp_c_max')) + ' C max'}.")
    if tel.get("igpu_mean") is not None:
        lines.append(f"Intel Arc iGPU: {tel['igpu_mean']:.0f}% mean busiest-engine utilization. NPU utilization is not "
                     f"exposed by Windows performance counters on this machine; NPU throughput comes from the lane itself.")
    lines.append(f"RAM peak {tel.get('ram_used_gib_max')} GiB of 23.4 (swap {tel.get('swap_used_gib_max')} GiB); disk write "
                 f"{tel.get('disk_write_mbs_mean')} MB/s mean, {tel.get('disk_write_mbs_max')} MB/s peak.")
    n = len(run.get("guard_interventions") or [])
    lines.append(f"Watchdog interventions: {n} (unleashed mode: only the 10 GB disk floor can act)." if run["meta"]["mode"] != "safe"
                 else f"Watchdog interventions: {n} (safe mode).")
    return lines


def write_peak_report(runs: list[dict]) -> Path:
    out = REPO / "docs" / "PEAK_REPORT.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not runs:
        out.write_text("# Peak report\n\nNo runs yet.\n")
        return out
    latest = runs[-1]
    # Reference throughput per lane: the first sustain that has that lane.
    ref: dict[str, float] = {}
    for r in runs:
        for s in r["steps"]:
            if s["phase"] == "sustain" and s["ok"] and s["lane"] not in ref and s["throughput"]:
                ref[s["lane"]] = s["throughput"]
    L = ["# Peak report", "",
         "Generated by `remixer bench report` from `reports/peak/*/summary.json`. Do not edit by hand; "
         "the narrative lives in `docs/PEAK_NOTES.md`.", ""]
    L += [f"Latest run: `reports/peak/{latest['meta']['ts']}/` ({latest['meta'].get('label') or 'unlabelled'}), mode "
          f"**{latest['meta']['mode']}**, lanes {', '.join(latest['meta']['lanes'])}, power plan: "
          f"{latest['meta'].get('power_plan', '?').split('(')[-1].rstrip(')')}.", ""]
    L += ["## Verdict (latest run)", ""] + [f"- {x}" for x in verdict(latest)] + [""]
    # headline per lane: best throughput ever, isolated and under full load
    L += ["## Peak throughput per stage", "", "| Lane | Stage | Best isolated | Config | Best with all lanes on | Config | Unit |",
          "|---|---|---:|---|---:|---|---|"]
    lanes = sorted({s["lane"] for r in runs for s in r["steps"]})
    stage = {"gpu": "Demucs separation", "cpu": "render storm (stretch/shift/mix)", "npu": "taste scorer (OpenVINO)"}
    for ln in lanes:
        iso = [s for r in runs for s in r["steps"] if s["lane"] == ln and s["ok"] and s["phase"].startswith("ramp:") and s["phase"] != "ramp:all"]
        allon = [s for r in runs for s in r["steps"] if s["lane"] == ln and s["ok"] and s["phase"] in ("ramp:all", "sustain")]
        bi = max(iso, key=lambda s: s["throughput"], default=None)
        ba = max(allon, key=lambda s: s["throughput"], default=None)
        L.append(f"| {ln} | {stage.get(ln, ln)} | {_fmt(bi and bi['throughput'], 2)} | {_cfg(bi['config']) if bi else '-'} | "
                 f"{_fmt(ba and ba['throughput'], 2)} | {_cfg(ba['config']) if ba else '-'} | {(bi or ba or {}).get('unit', '')} |")
    L += [""]
    # maxima over all runs
    def mx(key):
        vals = [r["overall"].get(key) for r in runs if r["overall"].get(key) is not None]
        return max(vals) if vals else None
    L += ["## Maxima across all runs", "",
          f"- VRAM {_fmt(mx('vram_used_gib_max'), 2)} GiB, RAM {_fmt(mx('ram_used_gib_max'), 2)} GiB, swap {_fmt(mx('swap_used_gib_max'), 2)} GiB",
          f"- GPU temp {_fmt(mx('gpu_temp_c_max'))} C, GPU power {_fmt(mx('gpu_power_w_max'))} W, CPU temp {_fmt(mx('cpu_temp_c_max'))} C",
          f"- Disk read {_fmt(mx('disk_read_mbs_max'))} MB/s, write {_fmt(mx('disk_write_mbs_max'))} MB/s", ""]
    # tuning rounds
    L += ["## Tuning rounds (sustained, all lanes on)", "",
          "Score = mean over lanes of sustained throughput / that lane's first sustained throughput. "
          "The hunt stops when two consecutive rounds improve the score by less than 3 %.", "",
          "| Run | Label | Lanes | Sustain | Config | Score | Change |", "|---|---|---|---:|---|---:|---:|"]
    prev = None
    deltas = []
    for r in runs:
        sc = sustain_score(r, ref)
        if sc is None:
            continue
        cfg = "; ".join(f"{s['lane']}: {_cfg(s['config'])}" for s in r["steps"] if s["phase"] == "sustain")
        d = None if prev is None else (sc - prev) / prev
        if d is not None:
            deltas.append(d)
        L.append(f"| {r['meta']['ts']} | {r['meta'].get('label') or ''} | {', '.join(r['meta']['lanes'])} | "
                 f"{_fmt((r['meta'].get('sustain_s') or 0) / 60, 0)} min | {cfg} | {sc:.3f} | {'-' if d is None else f'{100 * d:+.1f}%'} |")
        prev = sc
    converged = len(deltas) >= 2 and all(abs(d) < 0.03 for d in deltas[-2:])
    L += ["", f"Converged: **{'yes' if converged else 'no'}**" +
          (" (last two rounds changed the score by less than 3 %)." if converged else "."), ""]
    # every configuration tried
    L += ["## Every configuration tried", "",
          "| Run | Phase | Lane | Config | Seconds | OK | Throughput | Unit | GPU util mean | CPU util mean | iGPU mean | GPU temp max | GPU W mean | SM MHz mean | CPU MHz eff |",
          "|---|---|---|---|---:|---|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in runs:
        for s in r["steps"]:
            t = s.get("telemetry") or {}
            L.append(f"| {r['meta']['ts']} | {s['phase']} | {s['lane']} | {_cfg(s['config'])} | {s['seconds']:.0f} | "
                     f"{'yes' if s['ok'] else 'NO'} | {_fmt(s['throughput'], 2)} | {s['unit']} | {_fmt(t.get('gpu_util_mean'))} | "
                     f"{_fmt(t.get('cpu_util_mean'))} | {_fmt(t.get('igpu_mean'))} | {_fmt(t.get('gpu_temp_c_max'))} | "
                     f"{_fmt(t.get('gpu_power_w_mean'))} | {_fmt(t.get('gpu_sm_mhz_mean'), 0)} | {_fmt(t.get('cpu_mhz_eff_mean'), 0)} |")
    L += ["", "## Knees found", ""]
    for r in runs:
        if not r.get("ramp"):
            continue
        L.append(f"- `{r['meta']['ts']}`: isolated " + "; ".join(
            f"{ln}: {('level ' + str(int(k['level'] * 100)) + '% (' + _cfg(k['config']) + ', ' + _fmt(k['throughput'], 2) + ' ' + k['unit'] + ')') if k else 'none'}"
            for ln, k in r["ramp"]["isolated_knees"].items()) +
            (f"; combined knee {int(r['ramp']['combined_knee']['level'] * 100)}%" if r["ramp"].get("combined_knee") else ""))
    L += ["", "## Artifacts", ""] + [f"- `reports/peak/{r['meta']['ts']}/`: summary.json, steps.json, telemetry/*.parquet, "
                                      f"dashboard.html, {', '.join(r['charts'])}" for r in runs] + [""]
    out.write_text("\n".join(L), encoding="utf-8")
    return out


def write_report(run: Path) -> Path:
    summarize(run)
    return write_peak_report(all_runs())

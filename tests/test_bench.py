"""Bench helpers: knee detection, lane output parsing, durations, report generation."""
from __future__ import annotations

import json

import pyarrow as pa
import pyarrow.parquet as pq

from remixer.bench.cli import parse_duration
from remixer.bench.report import summarize, write_peak_report
from remixer.bench.stress import Lanes, Step, knee, last_json


def st(level, thr, ok=True):
    return Step(phase="ramp:gpu", lane="gpu", level=level, config={}, seconds=60, tag="", ok=ok, throughput=thr)


def test_knee_is_last_level_with_real_gain():
    assert knee([st(.25, 10), st(.5, 18), st(.75, 18.3), st(1, 18.1)]).level == .5
    assert knee([st(.25, 10), st(.5, 20), st(.75, 30), st(1, 40)]).level == 1
    assert knee([st(.25, 10), st(.5, 20), st(.75, 0, ok=False), st(1, 99)]).level == .5
    assert knee([st(.25, 0, ok=False)]) is None


def test_last_json_single_and_indented():
    assert last_json('log\n{"a": 1}\n{"b": 2}\n') == {"b": 2}
    assert last_json('noise\n{\n  "results": [\n    1\n  ]\n}\n') == {"results": [1]}


def test_parse_lane_results():
    assert Lanes.parse("gpu", {"steady_rate_x": 60.5, "rate_x": 20}) == (60.5, "audio-s/s")
    assert Lanes.parse("cpu", {"audio_seconds_per_second": 12.0})[0] == 12.0
    assert Lanes.parse("npu", {"results": [{"inferences_per_second": 5}, {"inferences_per_second": 7}]})[0] == 12


def test_parse_duration():
    assert parse_duration("60m") == 3600 and parse_duration("90s") == 90 and parse_duration("2") == 2


def test_cpu_ramp_consumes_the_measured_lane_recommendation(tmp_path):
    from types import SimpleNamespace
    state = tmp_path / "cpu-peak/tuning/tuning.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"best": {"render": {"workers": 12}}}))
    profile = SimpleNamespace(data_dir=tmp_path, resources=SimpleNamespace(cpu_workers=17))
    lanes = Lanes(profile, tmp_path / "out", gpu_batch_max=10)
    args, config = lanes.cpu(1.0, 60)
    assert lanes.cpu_max == config["workers"] == 12
    assert args[-1] == "12"


def test_report_from_synthetic_run(tmp_path, monkeypatch):
    import remixer.bench.report as rep

    monkeypatch.setattr(rep, "REPO", tmp_path)
    run = tmp_path / "reports" / "peak" / "20260101-000000"
    (run / "telemetry").mkdir(parents=True)
    pq.write_table(pa.table({"ts": [float(i) for i in range(100)], "tag": ["sustain@100"] * 100,
                             "gpu_util": [95.0] * 100, "cpu_util": [92.0] * 100, "gpu_temp_c": [85.0] * 100,
                             "gpu_throttle_names": ["sw_thermal", ""] * 50,
                             "gpu_power_w": [50.0] * 99 + [590.0], "gpu_power_limit_w": [90.0] * 100}),
                   run / "telemetry" / "p.parquet")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "PEAK_NOTES.md").write_text("# Peak notes\n\nPlain verdict: heat-bound.\n")
    (run / "meta.json").write_text(json.dumps({"ts": "20260101-000000", "lanes": ["gpu"], "mode": "unleashed",
                                               "sustain_s": 90, "power_plan": "x (Balanced)"}))
    (run / "steps.json").write_text(json.dumps([{"phase": "sustain", "lane": "gpu", "level": 1.0, "config": {"batch": 10},
                                                 "seconds": 90, "tag": "sustain@100", "t_start": 0, "t_end": 99,
                                                 "ok": True, "throughput": 60.0, "unit": "audio-s/s", "result": {},
                                                 "error": ""}]))
    s = summarize(run)
    assert s["steps"][0]["telemetry"]["gpu_util_mean"] == 95.0
    assert abs(s["steps"][0]["telemetry"]["throttle_sw_thermal_frac"] - 0.5) < 0.02
    text = write_peak_report([s]).read_text()
    assert "| gpu | Demucs separation" in text and "sw_thermal 5" in text
    assert s["steps"][0]["telemetry"]["gpu_power_w_max"] == 50.0  # 590 W > 2x the 90 W limit: invalid reading
    assert "Plain verdict: heat-bound." in text and "# Peak notes" not in text


def test_heavy_gpu_steps_use_model_pass_unit():
    heavy = {"stage": "separate_heavy", "steady_rate_x": 7.33, "model_rate_x": 58.62}
    assert Lanes.parse("gpu", heavy) == (58.62, "model-pass audio-s/s")
    assert Lanes.parse("gpu", {"stage": "separate", "steady_rate_x": 61.0, "model_rate_x": 61.0}) == (61.0, "audio-s/s")


def test_cool_preset_caps_lanes_and_watch_thresholds(tmp_path):
    import argparse

    from remixer.bench.stress import Limits, ThermalWatch, limits_from_args
    from remixer.config import load_profile

    lim = limits_from_args(argparse.Namespace(cool=True, cpu_max_workers=6))
    assert (lim.cpu_workers, lim.gpu_batch, lim.igpu, lim.heavy_gpu) == (6, 8, False, False)
    lanes = Lanes(load_profile(), tmp_path, gpu_batch_max=10, plan={"cpu": list(range(6, 20))}, limits=lim)
    assert lanes.cpu(1.0, 60)[1]["workers"] == 6
    assert lanes.gpu(1.0, 60, mode="loop")[1] == {"batch": 8, "mode": "cycle"}
    assert lanes.npu(1.0, 60)[1]["devices"] == ["NPU"]
    w = ThermalWatch(Limits(cpu_limit_c=97, gpu_limit_c=90), {}, [])
    assert w._over(97.5, 70) and w._over(80, 91) and not w._over(96, 89)
    assert not w._cool(92, 70) and w._cool(88, 81) and not w._cool(None, 83)
    assert limits_from_args(argparse.Namespace(unleashed=True)) == Limits()

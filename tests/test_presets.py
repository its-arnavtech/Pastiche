"""The stable preset is the default; --unleashed is explicit and warns (decision 0030)."""
import argparse

import pytest

from remixer.config import load_profile
from remixer.guards import Guard, Readings
from remixer.presets import SENSOR_MAX_C, STABLE_DEFAULTS, UNLEASHED_WARNING, current_mode, worker_cap


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("REMIXER_UNLEASHED", raising=False)
    monkeypatch.delenv("REMIXER_SAFE", raising=False)


def test_stable_is_the_default_and_caps_cpu_workers(data_dir):
    p = load_profile()
    assert p.mode == "stable" and current_mode() == "stable"
    assert p.resources.cpu_workers <= 8 and worker_cap() == 8


def test_cpu_cutoff_is_below_the_sensor_maximum():
    assert STABLE_DEFAULTS["cpu_limit_c"] == 93.0 < SENSOR_MAX_C == 95.9


def test_unleashed_lifts_the_caps(data_dir, monkeypatch):
    monkeypatch.setenv("REMIXER_UNLEASHED", "1")
    p = load_profile()
    assert p.mode == "unleashed" and worker_cap() is None
    assert p.resources.cpu_workers == max(1, p.resources.logical_cores - p.resources.gpu_feeders - p.resources.reserve)


def test_enable_unleashed_prints_the_warning(capsys, monkeypatch):
    from remixer.presets import enable_unleashed

    monkeypatch.setenv("REMIXER_UNLEASHED", "0")  # teardown restores the original (absent) state
    enable_unleashed()
    assert "WARNING" in capsys.readouterr().err and "power-off" in UNLEASHED_WARNING
    assert current_mode() == "unleashed"


def test_bench_defaults_to_the_stable_preset_and_unleashed_removes_it():
    from remixer.bench.stress import limits_from_args

    lim = limits_from_args(argparse.Namespace())
    assert (lim.cpu_workers, lim.gpu_batch, lim.igpu, lim.heavy_gpu) == (8, 8, False, False)
    assert (lim.cpu_limit_c, lim.gpu_limit_c, lim.cooldown_c) == (93.0, 94.0, 82.0)
    off = limits_from_args(argparse.Namespace(unleashed=True))
    assert (off.cpu_workers, off.gpu_batch, off.cpu_limit_c, off.heavy_gpu) == (0, 0, 0.0, True)


def test_stable_guard_reduces_on_median_not_single_spike(tmp_path):
    def sensors(temps):
        it = iter(temps)
        return lambda _d: Readings(free_disk_gb=100.0, cpu_temp_c=next(it))

    spiky = Guard(tmp_path, "stable", sensors=sensors([70, 97, 71, 72, 70]))
    assert [spiky.check().action for _ in range(5)] == ["ok"] * 5  # one boost spike does not act
    hot = Guard(tmp_path, "stable", sensors=sensors([94, 94, 95, 95, 95]))
    assert [hot.check().action for _ in range(5)][-1] == "reduce"
    free = Guard(tmp_path, "unleashed", sensors=sensors([99, 99, 99]))
    assert [free.check().action for _ in range(3)] == ["ok"] * 3

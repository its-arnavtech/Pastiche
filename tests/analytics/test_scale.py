import pytest

pytest.importorskip("duckdb")
pytest.importorskip("pyarrow")

from remixer.analytics.heatmap import build_heatmap  # noqa: E402
from remixer.analytics.scale import (  # noqa: E402
    build_heatmap_parquet, durations_from_parquet, iter_parquet_sessions, run_scale,
    write_events_parquet,
)
from remixer.analytics.simulate import simulate  # noqa: E402


@pytest.fixture(scope="module")
def sim():
    return simulate(n_tracks=30, n_sessions=150, seed=21)


@pytest.fixture(scope="module")
def parquet(sim, tmp_path_factory):
    path = tmp_path_factory.mktemp("ev") / "events.parquet"
    assert write_events_parquet([sim.events], path, rows_per_group=1000) == len(sim.events)
    return path


def test_parquet_sessions_preserve_order(sim, parquet):
    got = [e.event_id for s in iter_parquet_sessions(parquet) for e in s]
    want = [e.event_id for e in sorted(sim.events, key=lambda e: (e.session_id, e.wall_time))]
    assert got == want


def test_parquet_durations_match_simulator(sim, parquet):
    assert durations_from_parquet(parquet) == {t.key: t.duration_ms for t in sim.library
                                               if any(e.version_key == t.key for e in sim.events)}


@pytest.mark.parametrize("workers", [1, 3])
def test_parquet_build_equals_in_memory_build(sim, parquet, workers):
    hb, timing = build_heatmap_parquet(parquet, workers=workers)
    assert timing["events"] == len(sim.events)
    assert hb.to_rows() == build_heatmap(sim.events).to_rows()


@pytest.mark.scale
def test_scale_multi_million_events(tmp_path, report):
    r = run_scale(2_000_000, tmp_path)
    report(f"scale: {r}")
    assert r["events"] >= 2_000_000
    assert r["precision"] >= 0.95 and r["recall"] >= 0.97

"""Config, adapters, job queue and guards."""
from __future__ import annotations

import multiprocessing as mp
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from remixer import PROJECT_NAME
from remixer.adapters import build
from remixer.adapters.sqlite_queue import SqliteJobQueue
from remixer.config import compute_resources, load_profile
from remixer.guards import SAFE, Guard, Readings, purge_caches


def test_project_name():
    assert PROJECT_NAME == "StemDNA"


def test_resources_from_core_count():
    r = compute_resources({"reserve": {"logical_cores": 1}, "gpu_lane": {"feeder_cores": 4}}, logical=22)
    assert (r.gpu_feeders, r.reserve, r.cpu_workers) == (4, 1, 17)
    assert compute_resources({"reserve": {"logical_cores": 0}}, logical=8).reserve == 1  # never zero
    small = compute_resources({}, logical=4)
    assert small.cpu_workers >= 1 and small.gpu_feeders <= 2


def test_profile_defaults_and_overrides(data_dir, monkeypatch):
    p = load_profile()
    assert p.mode == "unleashed" and p["adapters"]["catalog"] == "sqlite"
    assert p.path("catalog") == data_dir / "catalog.sqlite"
    assert load_profile(overrides={"gpu": {"fp16": False}})["gpu"]["fp16"] is False
    monkeypatch.setenv("REMIXER_SAFE", "1")
    assert load_profile().mode == "safe"


def test_blobstore_content_addressed(data_dir):
    b = build().blobs
    k1 = b.put(b"hello", "stems", ".wav")
    assert k1 == b.put(b"hello", "stems", ".wav") and b.get(k1) == b"hello"
    src = data_dir / "src.bin"
    src.write_bytes(b"abc")
    k2 = b.put_file(src)
    assert src.exists() and b.get(k2) == b"abc"  # copied, source untouched


def test_catalog_upsert_and_query(data_dir):
    c = build().catalog
    c.upsert("tracks", {"track_id": "t1", "title": "a", "synthetic": 1}, key=["track_id"])
    c.upsert("tracks", {"track_id": "t1", "title": "b", "synthetic": 1}, key=["track_id"])
    assert c.get("tracks", track_id="t1")["title"] == "b"
    assert c.query("SELECT COUNT(*) n FROM tracks")[0]["n"] == 1


def test_event_sink_append_only(data_dir):
    e = build().events
    e.append("playback", [{"event_id": "1", "event_type": "play", "position_ms": 0}])
    e.append("playback", [{"event_id": "2", "event_type": "pause", "position_ms": 500}])
    rows = e.read("playback", "position_ms > 0")
    assert [r["event_id"] for r in rows] == ["2"]
    assert len(list((data_dir / "events" / "playback").glob("*.parquet"))) == 2


def test_vector_index_roundtrip(data_dir):
    a = build()
    idx = a.vector_index("t", dim=8)
    v = np.eye(8, dtype=np.float32)
    idx.add(list(range(8)), v)
    ids, _ = idx.search(v[3:4], k=1)
    assert ids[0, 0] == 3
    idx.save()
    assert len(a.vector_index("t", dim=8)) == 8


def test_queue_idempotent_lease_ack(tmp_path):
    q = SqliteJobQueue(tmp_path / "q.sqlite")
    assert q.enqueue("sep", "h1", {"x": 1}) and not q.enqueue("sep", "h1")
    jobs = q.lease("sep", "w1", n=5)
    assert [j.key for j in jobs] == ["h1"] and q.lease("sep", "w2") == []
    q.ack(jobs[0].id, {"ok": True})
    assert q.counts("sep") == {"done": 1}


def test_queue_lease_expiry_and_retries(tmp_path):
    q = SqliteJobQueue(tmp_path / "q.sqlite", max_attempts=2)
    q.enqueue("k", "a")
    j = q.lease("k", "w1", lease_s=0.05)[0]
    time.sleep(0.1)
    j2 = q.lease("k", "w2")[0]  # expired lease is reclaimed
    assert j2.id == j.id and j2.attempts == 2
    q.fail(j2.id, "boom")
    assert q.counts("k") == {"failed": 1}  # attempts exhausted


def _worker(path, owner, out):
    q = SqliteJobQueue(Path(path))
    got = []
    while jobs := q.lease("k", owner, n=3):
        for j in jobs:
            got.append(j.key)
            q.ack(j.id)
    out.put(got)


def test_queue_multiprocess_no_double_lease(tmp_path):
    path = tmp_path / "q.sqlite"
    q = SqliteJobQueue(path)
    q.enqueue_many("k", [(f"j{i}", {}) for i in range(200)])
    ctx = mp.get_context("spawn")
    out = ctx.Queue()
    procs = [ctx.Process(target=_worker, args=(str(path), f"w{i}", out)) for i in range(4)]
    for p in procs:
        p.start()
    keys = [k for _ in procs for k in out.get(timeout=60)]
    for p in procs:
        p.join(timeout=30)
    assert sorted(keys) == sorted(f"j{i}" for i in range(200))


KILL_SCRIPT = """
import sys, time
from pathlib import Path
from remixer.adapters.sqlite_queue import SqliteJobQueue
q = SqliteJobQueue(Path(sys.argv[1]))
q.lease("k", "victim", n=1, lease_s=0.5)
print("leased", flush=True)
time.sleep(60)
"""


def test_queue_survives_forced_kill(tmp_path):
    path = tmp_path / "q.sqlite"
    SqliteJobQueue(path).enqueue("k", "only")
    p = subprocess.Popen([sys.executable, "-c", KILL_SCRIPT, str(path)], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "leased"
    p.kill()
    p.wait()
    time.sleep(0.6)
    jobs = SqliteJobQueue(path).lease("k", "survivor")
    assert [j.key for j in jobs] == ["only"]


def fake(**kw):
    return lambda d: Readings(**{"free_disk_gb": 500.0, **kw})


def test_unleashed_never_acts_on_thermals_or_battery(tmp_path):
    g = Guard(tmp_path, "unleashed", sensors=fake(gpu_temp_c=99, cpu_temp_c=110, on_battery=True,
                                                   gpu_throttle=["hw_thermal"]))
    d = g.check()
    assert d.action == "ok" and d.scale == 1.0 and g.interventions == []


def test_unleashed_disk_floor_purges_cache_only(tmp_path):
    (tmp_path / "cache" / "sub").mkdir(parents=True)
    (tmp_path / "cache" / "sub" / "x.bin").write_bytes(b"0" * 1000)
    (tmp_path / "keep.bin").write_bytes(b"1")
    g = Guard(tmp_path, "unleashed", sensors=fake(free_disk_gb=5.0))
    assert g.check().action == "pause_writes"
    assert not (tmp_path / "cache" / "sub").exists() and (tmp_path / "keep.bin").exists()


def test_safe_mode_limits(tmp_path):
    assert Guard(tmp_path, "safe", sensors=fake(gpu_temp_c=91)).check().action == "reduce"
    assert Guard(tmp_path, "safe", sensors=fake(gpu_temp_c=96)).check().action == "pause"
    assert Guard(tmp_path, "safe", sensors=fake(cpu_temp_c=101)).check().action == "reduce"
    assert Guard(tmp_path, "safe", sensors=fake(on_battery=True)).check().action == "pause"
    assert Guard(tmp_path, "safe", sensors=fake(free_disk_gb=20)).check().action == "pause_writes"
    assert SAFE.disk_floor_gb == 25.0


def test_purge_refuses_outside_data_dir(tmp_path):
    assert purge_caches(tmp_path / "nonexistent") == 0


def test_cli_info(data_dir):
    r = subprocess.run([sys.executable, "-m", "remixer.cli", "info"], capture_output=True, text=True,
                       env={**os.environ, "REMIXER_DATA_DIR": str(data_dir)})
    assert r.returncode == 0, r.stderr
    assert '"project": "StemDNA"' in r.stdout


def test_core_plan_splits_meteor_lake_topology_into_disjoint_lane_sets():
    from remixer.adapters.local_compute import core_plan
    from remixer.config import Resources

    # Core Ultra 9 185H as Windows reports it: P-cores 0-1 and 10-19 (HT pairs), E 2-9, LP-E 20-21
    rows = [{"group": 0, "logical_processor": i, "core_index": (i if i < 10 or i > 19 else i - (i % 2)),
             "efficiency_class": 1 if (i < 2 or 10 <= i <= 19) else 0} for i in range(22)]
    rows[1]["core_index"] = 0
    plan = core_plan(Resources(logical_cores=22, physical_cores=16, reserve=1, gpu_feeders=4, npu_host_threads=1),
                     {"rows": rows, "reason": None})
    assert plan == {"gpu": [0, 1, 2, 3, 4, 5], "cpu": [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19],
                    "npu": [20], "reserve": [21]}
    assert core_plan(Resources(logical_cores=8, physical_cores=8), {"rows": [], "reason": "no CPU sets"}) == {}


def test_pin_from_env_applies_and_ignores_missing(monkeypatch):
    import psutil

    from remixer.adapters.local_compute import AFFINITY_ENV, pin_from_env

    monkeypatch.delenv(AFFINITY_ENV, raising=False)
    assert pin_from_env() is None
    before = psutil.Process().cpu_affinity()
    try:
        monkeypatch.setenv(AFFINITY_ENV, ",".join(map(str, before[:2])))
        assert pin_from_env() == before[:2]
        assert psutil.Process().cpu_affinity() == before[:2]
    finally:
        psutil.Process().cpu_affinity(before)

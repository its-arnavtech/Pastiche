"""Two tenants on the same profile: nothing tenant A writes is visible to tenant B (spec section 6).

``assert_isolated`` is the check; ``test_the_check_catches_a_leak`` proves it fails when two
handles share data, so a profile that leaks cannot pass by accident.
"""
import numpy as np
import pytest

from remixer.analytics.simulate import simulate


def write_everything(a) -> dict:
    events = simulate(n_tracks=3, n_sessions=4, seed=11).events
    a.events.append("playback", [e.to_row() for e in events])
    a.catalog.upsert("tracks", {"track_id": "secret-track", "title": "A only"}, key=["track_id"])
    a.catalog.insert("rating_events", {"event_id": "r1", "target_kind": "track", "target_id": "secret-track",
                                       "rating": "down", "wall_time": "2026-10-29T00:00:00Z"})
    a.jobs.enqueue("separate", "secret-track", {"tenant": "a"})
    blob = a.blobs.put(b"tenant A private stem", namespace="stems")
    try:
        import hnswlib  # noqa: F401
        idx = a.vector_index("stems", 8)
        idx.add([42], np.ones((1, 8), dtype=np.float32))
        idx.save()
        vectors = True
    except ImportError:
        vectors = False
    return {"blob": blob, "vectors": vectors}


def assert_isolated(a, b) -> None:
    written = write_everything(a)
    assert b.events.read("playback") == [], "events leak"
    assert b.catalog.get("tracks", track_id="secret-track") is None, "catalog rows leak"
    assert b.catalog.query("SELECT * FROM rating_events") == [], "ratings leak"
    assert b.jobs.lease("separate", owner="b") == [], "jobs leak"
    assert sum(b.jobs.counts().values()) == 0, "job counts leak"
    assert not b.blobs.exists(written["blob"]), "blobs leak"
    if written["vectors"]:
        assert len(b.vector_index("stems", 8)) == 0, "vectors leak"


def test_tenants_are_isolated(open_tenant):
    assert_isolated(open_tenant("tenant-a"), open_tenant("tenant-b"))


def test_isolation_holds_in_both_directions(open_tenant):
    assert_isolated(open_tenant("tenant-b"), open_tenant("tenant-a"))


def test_the_check_catches_a_leak(open_tenant):
    with pytest.raises(AssertionError, match="leak"):
        assert_isolated(open_tenant("same"), open_tenant("same"))


def test_tenant_a_still_sees_its_own_data(open_tenant):
    a = open_tenant("tenant-a")
    written = write_everything(a)
    assert open_tenant("tenant-a").catalog.get("tracks", track_id="secret-track")["title"] == "A only"
    assert open_tenant("tenant-a").blobs.exists(written["blob"])

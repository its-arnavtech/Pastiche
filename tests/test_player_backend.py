"""Real player backend (remixer.server.app) without a browser: the decision-0016 routes on real adapters."""
import copy

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from remixer.adapters import build  # noqa: E402
from remixer.analytics.events import Event  # noqa: E402
from remixer.config import DEFAULT_PROFILE, Profile, compute_resources  # noqa: E402
from remixer.server.app import PlayerBackend, create_app, seed_demo  # noqa: E402


@pytest.fixture
def client(tmp_path):
    a = build(Profile(raw=copy.deepcopy(DEFAULT_PROFILE), resources=compute_resources({}), data_dir=tmp_path))
    seed_demo(a)
    with TestClient(create_app(PlayerBackend(a, events_url=None))) as c:
        c.adapters = a
        yield c
    a.catalog.close()


def event(i: int, kind: str = "play", track: str = "src-aurora") -> dict:
    return {"event_id": f"e{i}", "session_id": "s1", "track_id": track, "track_version": "v1", "event_type": kind,
            "position_ms": 1000 * i, "wall_time": 1_790_000_000_000 + i, "source_kind": "source",
            "client_info": {"ui": "test"}, "payload": {}}


def test_tracks_config_and_static(client):
    tracks = client.get("/api/tracks").json()
    assert [t["track_id"] for t in tracks] == ["src-aurora", "gen-0001", "src-basalt", "gen-0002"]
    assert tracks[1]["source_kind"] == "generated" and tracks[0]["audio_url"] == "/audio/src-aurora.wav"
    assert client.get("/api/config").json()["events_url"] == "/api/events"
    assert client.get("/").headers["content-type"].startswith("text/html")
    for bad in ("/mock_server.py", "/../pyproject.toml", "/nope.html"):
        assert client.get(bad).status_code == 404
    assert client.get("/api/tracks").headers["cache-control"] == "no-store"


def test_audio_supports_ranges(client):
    full = client.get("/audio/src-aurora.wav")
    assert full.status_code == 200 and full.content[:4] == b"RIFF"
    part = client.get("/audio/src-aurora.wav", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == full.content[100:200]
    assert part.headers["content-range"] == f"bytes 100-199/{len(full.content)}"
    assert client.get("/audio/src-aurora.wav", headers={"Range": f"bytes={len(full.content)}-"}).status_code == 416
    assert client.get("/audio/nope.wav").status_code == 404


def test_events_round_trip_in_order_and_feed_the_nightly_job(client):
    rows = [event(i) for i in range(5)] + [event(9, "rate_down")]
    for r in rows[:3]:
        assert client.post("/api/events", json=r).json() == {"accepted": 1, "errors": []}
    assert client.post("/api/events", json=rows[3:]).json()["accepted"] == 3
    assert client.get("/api/events").json() == rows
    assert client.get("/api/ratings").json()["src-aurora"]["rating"] == "down"
    stored = [Event.from_row(r) for r in client.adapters.events.read("playback")]   # what run_job reads
    assert sorted(e.event_id for e in stored) == sorted(r["event_id"] for r in rows)
    bad = client.post("/api/events", json=[event(10), {"event_id": "x"}])
    assert bad.status_code == 400 and bad.json()["accepted"] == 0
    assert len(client.get("/api/events").json()) == len(rows)


def test_cors_preflight_for_cross_origin_events(client):
    r = client.options("/api/events", headers={"Origin": "http://elsewhere", "Access-Control-Request-Method": "POST",
                                               "Access-Control-Request-Headers": "Content-Type"})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] in ("*", "http://elsewhere")


def test_inbox_comes_from_the_nightly_state_with_answers_applied(client):
    items = client.get("/api/insights").json()
    assert items and all(i["answer"] is None for i in items)
    first = items[0]
    answer = event(20, "insight_yes", first["track_id"]) | {
        "track_version": first["track_version"], "payload": {"insight_id": first["insight_id"]}}
    r = client.post("/api/events", json=answer)
    assert r.status_code == 200, r.json()
    after = {i["insight_id"]: i for i in client.get("/api/insights").json()}
    assert after[first["insight_id"]]["answer"] == "yes"

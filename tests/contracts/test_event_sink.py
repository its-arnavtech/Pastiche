"""EventSink: append-only. Read order is not part of the contract; consumers sort (see sort_events)."""
from remixer.analytics.events import Event, sort_events
from remixer.analytics.simulate import simulate


def key(rows):
    return sorted(r["event_id"] for r in rows)


def test_append_returns_count_and_read_returns_everything(adapters):
    s = adapters.events
    assert s.append("playback", []) == 0
    assert s.read("playback") == []
    assert s.append("playback", [{"event_id": "e1", "v": 1}, {"event_id": "e2", "v": 2}]) == 2
    assert s.append("playback", [{"event_id": "e3", "v": 3}]) == 1
    assert key(s.read("playback")) == ["e1", "e2", "e3"]


def test_appends_never_rewrite_history(adapters):
    s = adapters.events
    s.append("playback", [{"event_id": "e1", "v": 1}])
    s.append("playback", [{"event_id": "e1", "v": 2}])  # same id again: both rows stay
    assert sorted(r["v"] for r in s.read("playback")) == [1, 2]


def test_streams_are_separate(adapters):
    s = adapters.events
    s.append("playback", [{"event_id": "p"}])
    s.append("ratings", [{"event_id": "r"}])
    assert key(s.read("playback")) == ["p"]
    assert key(s.read("ratings")) == ["r"]
    assert s.read("never-written") == []


def test_where_filter(adapters):
    s = adapters.events
    s.append("playback", [{"event_id": f"e{i}", "v": i} for i in range(10)])
    assert key(s.read("playback", where="v >= 7")) == ["e7", "e8", "e9"]


def test_t014_events_round_trip_exactly(adapters):
    events = simulate(n_tracks=6, n_sessions=20, seed=3).events
    half = len(events) // 2
    adapters.events.append("playback", [e.to_row() for e in events[half:]])  # out of order on purpose
    adapters.events.append("playback", [e.to_row() for e in events[:half]])
    back = [Event.from_row(r) for r in adapters.events.read("playback")]
    assert sort_events(back) == sort_events(events)


def test_durable_across_reopen(open_tenant):
    open_tenant("tenant-a").events.append("playback", [{"event_id": "kept"}])
    assert key(open_tenant("tenant-a").events.read("playback")) == ["kept"]

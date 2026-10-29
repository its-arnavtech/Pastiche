import pytest

from remixer.analytics.events import (
    EVENT_FIELDS, Event, EventValidationError, parse_wall_time, sort_events, validate_event,
)


def good(**kw):
    d = {"event_id": "e1", "session_id": "s1", "track_id": "t1", "track_version": "v1",
         "event_type": "play", "position_ms": 0, "wall_time": 1_790_000_000_000,
         "source_kind": "generated", "client_info": {"ua": "x"}}
    d.update(kw)
    return d


def test_valid_event_roundtrip():
    e = Event.from_dict(good())
    assert validate_event(e.to_dict()) == []
    assert tuple(e.to_dict()) == EVENT_FIELDS
    assert Event.from_dict(e.to_dict()) == e


@pytest.mark.parametrize("bad, msg", [
    ({"event_type": "seek_fwd_10s"}, "event_type"),
    ({"source_kind": "radio"}, "source_kind"),
    ({"position_ms": -1}, "position_ms"),
    ({"position_ms": 1.5}, "position_ms"),
    ({"position_ms": True}, "position_ms"),
    ({"track_version": ""}, "track_version"),
    ({"wall_time": "yesterday"}, "wall_time"),
    ({"client_info": "x"}, "client_info"),
    ({"extra": 1}, "unknown fields"),
])
def test_invalid_events(bad, msg):
    errs = validate_event(good(**bad))
    assert any(msg in e for e in errs), errs
    with pytest.raises(EventValidationError):
        Event.from_dict(good(**bad))


def test_missing_required_field():
    d = good()
    del d["track_version"]
    assert validate_event(d) == ["missing track_version"]


def test_wall_time_iso_and_ms():
    assert parse_wall_time("2026-10-29T00:00:00Z") == parse_wall_time("2026-10-29T00:00:00")
    assert parse_wall_time(1_790_000_000_000) == 1_790_000_000_000


def test_sort_is_stable_for_equal_wall_times():
    a = Event.from_dict(good(event_id="a", event_type="seek_fwd_5s"))
    b = Event.from_dict(good(event_id="b", event_type="seek_fwd_5s"))
    assert [e.event_id for e in sort_events([a, b])] == ["a", "b"]

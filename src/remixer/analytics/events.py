"""Append-only playback/rating event envelope (spec section 5).

One envelope for every player control. Fields, in storage order:

    event_id, session_id, track_id, track_version, event_type, position_ms,
    wall_time, source_kind, client_info, payload

- ``wall_time`` is UTC epoch milliseconds (``Date.now()`` in the browser).
- ``position_ms`` is the playhead at the moment of the control, before any seek.
- Seeks are always exactly ``SEEK_MS``; the target is derived, never stored.
- ``payload`` is optional and only used by rating/insight events (decision 0006).
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

SEEK_MS = 5000

PLAYBACK_EVENT_TYPES = (
    "play", "pause", "seek_back_5s", "seek_fwd_5s", "next", "previous", "track_end",
)
RATING_EVENT_TYPES = ("rate_up", "rate_down", "rate_tired", "rate_clear")
INSIGHT_EVENT_TYPES = ("insight_yes", "insight_no", "insight_unsure")
EVENT_TYPES = PLAYBACK_EVENT_TYPES + RATING_EVENT_TYPES + INSIGHT_EVENT_TYPES
SOURCE_KINDS = ("source", "generated")

EVENT_FIELDS = (
    "event_id", "session_id", "track_id", "track_version", "event_type",
    "position_ms", "wall_time", "source_kind", "client_info", "payload",
)
REQUIRED_FIELDS = EVENT_FIELDS[:8]
JSON_FIELDS = ("client_info", "payload")
_STRING_FIELDS = ("event_id", "session_id", "track_id", "track_version")


class EventValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Event:
    event_id: str
    session_id: str
    track_id: str
    track_version: str
    event_type: str
    position_ms: int
    wall_time: int
    source_kind: str = "source"
    client_info: Mapping[str, Any] = field(default_factory=dict)
    payload: Mapping[str, Any] = field(default_factory=dict)

    @property
    def version_key(self) -> tuple[str, str]:
        return (self.track_id, self.track_version)

    @property
    def is_playback(self) -> bool:
        return self.event_type in PLAYBACK_EVENT_TYPES

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id, "session_id": self.session_id,
            "track_id": self.track_id, "track_version": self.track_version,
            "event_type": self.event_type, "position_ms": self.position_ms,
            "wall_time": self.wall_time, "source_kind": self.source_kind,
            "client_info": dict(self.client_info), "payload": dict(self.payload),
        }

    def to_row(self) -> dict[str, Any]:
        """Flat storage row: nested fields as compact JSON text (Parquet / EventSink layout)."""
        d = self.to_dict()
        for k in JSON_FIELDS:
            d[k] = json.dumps(d[k], separators=(",", ":"), sort_keys=True)
        return d

    @classmethod
    def from_row(cls, r: Mapping[str, Any]) -> "Event":
        d = {k: r[k] for k in EVENT_FIELDS if k in r}
        for k in JSON_FIELDS:
            if isinstance(d.get(k), str):
                d[k] = json.loads(d[k])
        return cls.from_dict(d)

    @property
    def seq(self) -> int:
        """Client emit order (``client_info.seq``); breaks wall-time ties when storage reorders rows."""
        s = self.client_info.get("seq") if self.client_info else None
        return s if isinstance(s, int) and not isinstance(s, bool) else -1

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Event":
        errors = validate_event(d)
        if errors:
            raise EventValidationError("; ".join(errors))
        return cls(
            event_id=d["event_id"], session_id=d["session_id"], track_id=d["track_id"],
            track_version=d["track_version"], event_type=d["event_type"],
            position_ms=int(d["position_ms"]), wall_time=parse_wall_time(d["wall_time"]),
            source_kind=d["source_kind"], client_info=dict(d.get("client_info") or {}),
            payload=dict(d.get("payload") or {}),
        )


def parse_wall_time(v: Any) -> int:
    """Epoch milliseconds from an int/float or an ISO-8601 string (naive means UTC)."""
    if isinstance(v, bool):
        raise EventValidationError("wall_time must be epoch ms or ISO-8601")
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        try:
            t = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError as e:
            raise EventValidationError(f"wall_time: {e}") from None
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return int(t.timestamp() * 1000)
    raise EventValidationError("wall_time must be epoch ms or ISO-8601")


def validate_event(d: Mapping[str, Any]) -> list[str]:
    """Return a list of problems (empty when the event is valid)."""
    if not isinstance(d, Mapping):
        return ["event must be an object"]
    errors = [f"missing {k}" for k in REQUIRED_FIELDS if k not in d]
    unknown = set(d) - set(EVENT_FIELDS)
    if unknown:
        errors.append(f"unknown fields {sorted(unknown)}")
    for k in _STRING_FIELDS:
        if k in d and (not isinstance(d[k], str) or not d[k]):
            errors.append(f"{k} must be a non-empty string")
    if "event_type" in d and d["event_type"] not in EVENT_TYPES:
        errors.append(f"event_type {d['event_type']!r} not in {EVENT_TYPES}")
    if "source_kind" in d and d["source_kind"] not in SOURCE_KINDS:
        errors.append(f"source_kind {d['source_kind']!r} not in {SOURCE_KINDS}")
    if "position_ms" in d:
        p = d["position_ms"]
        if isinstance(p, bool) or not isinstance(p, (int, float)) or p < 0 or p != int(p):
            errors.append("position_ms must be a non-negative integer")
    if "wall_time" in d:
        try:
            parse_wall_time(d["wall_time"])
        except EventValidationError as e:
            errors.append(str(e))
    for k in ("client_info", "payload"):
        if d.get(k) is not None and not isinstance(d[k], Mapping):
            errors.append(f"{k} must be an object")
    return errors


def sort_events(events: Iterable[Event]) -> list[Event]:
    """Session, wall time, then ``client_info.seq``; stable, so append order breaks remaining ties."""
    return sorted(events, key=lambda e: (e.session_id, e.wall_time, e.seq))


def group_sessions(events: Iterable[Event]) -> dict[str, list[Event]]:
    sessions: dict[str, list[Event]] = {}
    for e in sort_events(events):
        sessions.setdefault(e.session_id, []).append(e)
    return sessions

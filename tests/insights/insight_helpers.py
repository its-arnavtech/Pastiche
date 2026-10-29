"""Small synthetic histories for the insight-layer tests. Events are marked synthetic."""
from remixer.analytics.events import Event
from remixer.analytics.simulate import Player, TrackSpec

DAY = 86_400_000
T0 = 1_790_000_000_000  # 2026-09-21 12:26 UTC


def track(track_id: str = "song", duration_ms: int = 90_000) -> TrackSpec:
    return TrackSpec(track_id, "v1", duration_ms, "source")


def session(track_id: str, index: int, play, *, shuffle: bool = False, at_ms: int | None = None) -> list[Event]:
    p = Player(f"{track_id}-{index}", T0 + (at_ms if at_ms is not None else index * DAY),
               {"synthetic": True, "shuffle": shuffle})
    play(p, track(track_id))
    return p.events


def skip_at(p: Player, t: TrackSpec, at_ms: int, undo: bool = False) -> None:
    p.load(t).play().listen_to(at_ms)
    p.fwd()
    if undo:
        p.wait(800).back()
    p.listen_to(t.duration_ms).end()


def history_skipping(track_id: str, n: int, at_ms: int = 20_000, **kw) -> list[Event]:
    return [e for i in range(n) for e in session(track_id, i, lambda p, t: skip_at(p, t, at_ms), **kw)]


def answer_event(insight_id: str, kind: str, wall: int, track_id: str = "song") -> Event:
    return Event(f"ans-{insight_id}-{kind}-{wall}", "inbox", track_id, "v1", kind, 0, wall, "source",
                 {"synthetic": True}, {"insight_id": insight_id})

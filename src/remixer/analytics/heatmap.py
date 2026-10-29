"""Skip heatmap over 5-second windows and the candidate-window detector (spec section 5).

Per ``(track_id, track_version, window)`` the builder counts listens that ``reached`` the window
and, of those, how many ``played``, ``skipped``, ``replayed`` and ``undone`` it. The denominator of
every rate is ``reached``, never total listens. Keys include ``track_version`` so a re-rendered
recipe starts with a clean heatmap.

A window is a candidate when all of:

- the track version has at least ``min_track_listens`` listens (default 3);
- it was skipped at least ``min_skips`` times (default 2, so a single skip never qualifies);
- ``skipped / reached >= min_skip_rate`` (default 0.6, a clear majority);
- ``undone / reached <= max_undo_rate`` (default 0.2, undos are rare).

Candidates are hypotheses for the insights inbox; they never prompt the user.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Mapping

from .events import Event, group_sessions
from .interpret import (
    DEFAULT_CONFIG, InterpretConfig, Listen, VersionKey, interpret_session, resolve_durations,
    window_rows,
)

REACHED, PLAYED, SKIPPED, REPLAYED, UNDONE = range(5)


@dataclass(frozen=True)
class DetectorConfig:
    min_track_listens: int = 3
    min_skips: int = 2
    min_skip_rate: float = 0.6
    max_undo_rate: float = 0.2


DEFAULT_DETECTOR = DetectorConfig()


@dataclass(frozen=True)
class WindowStats:
    track_id: str
    track_version: str
    window_index: int
    start_ms: int
    end_ms: int
    track_listens: int
    reached: int
    played: int
    skipped: int
    replayed: int
    undone: int

    @property
    def skip_rate(self) -> float:
        return self.skipped / self.reached if self.reached else 0.0

    @property
    def undo_rate(self) -> float:
        return self.undone / self.reached if self.reached else 0.0

    def is_candidate(self, cfg: DetectorConfig = DEFAULT_DETECTOR) -> bool:
        return (self.track_listens >= cfg.min_track_listens
                and self.skipped >= cfg.min_skips
                and self.skip_rate >= cfg.min_skip_rate
                and self.undo_rate <= cfg.max_undo_rate)


class HeatmapBuilder:
    """Streaming accumulator; ``merge`` combines partial builders from parallel workers."""

    def __init__(self, cfg: InterpretConfig = DEFAULT_CONFIG):
        self.cfg = cfg
        self.listens: dict[VersionKey, int] = {}
        self.windows: dict[VersionKey, dict[int, list[int]]] = {}
        self.durations: dict[VersionKey, int] = {}

    def add_listen(self, listen: Listen) -> None:
        key = listen.key
        self.listens[key] = self.listens.get(key, 0) + 1
        if listen.duration_ms:
            self.durations[key] = listen.duration_ms
        wins = self.windows.setdefault(key, {})
        for w, _, _, played, skipped, replayed, undone in window_rows(listen, self.cfg):
            c = wins.get(w)
            if c is None:
                c = wins[w] = [0, 0, 0, 0, 0]
            c[REACHED] += 1
            c[PLAYED] += played
            c[SKIPPED] += skipped
            c[REPLAYED] += replayed
            c[UNDONE] += undone

    def add_session(self, events: list[Event], durations: Mapping[VersionKey, int] | None = None) -> None:
        for listen in interpret_session(events, self.cfg, durations):
            self.add_listen(listen)

    def add_events(self, events: Iterable[Event], durations: Mapping[VersionKey, int] | None = None) -> None:
        events = list(events)
        durs = resolve_durations(events, durations)
        for session in group_sessions(events).values():
            self.add_session(session, durs)

    def merge(self, other: "HeatmapBuilder") -> "HeatmapBuilder":
        for key, n in other.listens.items():
            self.listens[key] = self.listens.get(key, 0) + n
        self.durations.update(other.durations)
        for key, wins in other.windows.items():
            mine = self.windows.setdefault(key, {})
            for w, c in wins.items():
                m = mine.setdefault(w, [0, 0, 0, 0, 0])
                for i in range(5):
                    m[i] += c[i]
        return self

    def stats(self) -> Iterator[WindowStats]:
        w_ms = self.cfg.window_ms
        for key in sorted(self.windows):
            dur = self.durations.get(key)
            for w in sorted(self.windows[key]):
                c = self.windows[key][w]
                end = (w + 1) * w_ms
                yield WindowStats(key[0], key[1], w, w * w_ms, min(end, dur) if dur else end,
                                  self.listens.get(key, 0), *c)

    def candidates(self, cfg: DetectorConfig = DEFAULT_DETECTOR) -> list[WindowStats]:
        return [s for s in self.stats() if s.is_candidate(cfg)]

    def to_rows(self) -> list[dict]:
        return [dict(s.__dict__, skip_rate=s.skip_rate, undo_rate=s.undo_rate) for s in self.stats()]


def build_heatmap(events: Iterable[Event], cfg: InterpretConfig = DEFAULT_CONFIG,
                  durations: Mapping[VersionKey, int] | None = None) -> HeatmapBuilder:
    b = HeatmapBuilder(cfg)
    b.add_events(events, durations)
    return b


def detect_candidates(events: Iterable[Event], cfg: InterpretConfig = DEFAULT_CONFIG,
                      detector: DetectorConfig = DEFAULT_DETECTOR,
                      durations: Mapping[VersionKey, int] | None = None) -> list[WindowStats]:
    return build_heatmap(events, cfg, durations).candidates(detector)

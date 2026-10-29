"""Evidence for one candidate run: play history around it and what changes in the music there.

A *run* is a maximal group of adjacent candidate windows (T-014 ``WindowStats``) of one track version.
Per run, every listen of that version that reached it is reduced to a few flags (skipped, undone,
shuffle, local hour, first press position). The flags become the statistics that the Analyst and
the Skeptic read and that the deterministic confound rules check.

"What changes at that timestamp" comes from ``TrackFeatures``: stem activity, loudness, tempo and
section labels per 5-second window. In production these come from the catalog's analysis tables
(the nightly job, T-029, supplies them). Without features the request just has no changes.
"""
from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Protocol, Sequence

from remixer.analytics.events import Event, group_sessions
from remixer.analytics.heatmap import HeatmapBuilder, WindowStats
from remixer.analytics.interpret import (
    DEFAULT_CONFIG, InterpretConfig, Listen, VersionKey, interpret_session, resolve_durations, window_rows,
)

DAYPARTS = (("night", 0, 6), ("morning", 6, 12), ("afternoon", 12, 18), ("evening", 18, 24))
LOUDNESS_STEP_DB = 3.0
TEMPO_STEP = 0.03


@dataclass(frozen=True)
class WindowFeatures:
    index: int
    loudness_lufs: float | None = None
    tempo_bpm: float | None = None
    section: str | None = None
    stems: frozenset[str] = frozenset()


class TrackFeatures(Protocol):
    def window_features(self, track_id: str, track_version: str) -> Sequence[WindowFeatures] | None: ...


@dataclass
class StaticFeatures:
    """In-memory ``TrackFeatures``: ``{(track_id, track_version): [WindowFeatures, ...]}``."""
    table: Mapping[VersionKey, Sequence[WindowFeatures]] = field(default_factory=dict)

    def window_features(self, track_id: str, track_version: str) -> Sequence[WindowFeatures] | None:
        return self.table.get((track_id, track_version))


def changes_at(features: Sequence[WindowFeatures] | None, window: int) -> list[dict]:
    """What changes going into ``window`` compared with the window before it."""
    if window == 0:
        return [{"kind": "track_start", "detail": "the track starts"}]
    if not features:
        return []
    by = {f.index: f for f in features}
    cur, prev = by.get(window), by.get(window - 1)
    if cur is None or prev is None:
        return []
    out = []
    for s in sorted(cur.stems - prev.stems):
        out.append({"kind": "stem_entry", "detail": f"{s} enter"})
    for s in sorted(prev.stems - cur.stems):
        out.append({"kind": "stem_exit", "detail": f"{s} drop out"})
    if cur.loudness_lufs is not None and prev.loudness_lufs is not None:
        d = cur.loudness_lufs - prev.loudness_lufs
        if abs(d) >= LOUDNESS_STEP_DB:
            out.append({"kind": "loudness_jump", "detail": f"loudness {d:+.1f} dB"})
    if cur.tempo_bpm and prev.tempo_bpm and abs(cur.tempo_bpm / prev.tempo_bpm - 1) >= TEMPO_STEP:
        out.append({"kind": "tempo_change", "detail": f"tempo {prev.tempo_bpm:.0f} to {cur.tempo_bpm:.0f} BPM"})
    if cur.section and prev.section and cur.section != prev.section:
        out.append({"kind": "section_change", "detail": f"{prev.section} to {cur.section}"})
    return out


@dataclass(frozen=True)
class Run:
    track_id: str
    track_version: str
    first_window: int
    last_window: int
    start_ms: int
    end_ms: int
    track_listens: int

    @property
    def window_id(self) -> str:
        return f"{self.track_id}:{self.track_version}:{self.start_ms}-{self.end_ms}"

    @property
    def key(self) -> VersionKey:
        return (self.track_id, self.track_version)

    def overlaps(self, track_id: str, track_version: str, start_ms: int, end_ms: int) -> bool:
        return (track_id, track_version) == self.key and start_ms < self.end_ms and self.start_ms < end_ms


def runs_from_candidates(candidates: Iterable[WindowStats]) -> list[Run]:
    rows = sorted(candidates, key=lambda c: (c.track_id, c.track_version, c.window_index))
    out: list[Run] = []
    group: list[WindowStats] = []

    def flush():
        if group:
            a, b = group[0], group[-1]
            out.append(Run(a.track_id, a.track_version, a.window_index, b.window_index,
                           a.start_ms, b.end_ms, a.track_listens))
            group.clear()

    for c in rows:
        if group and (c.track_id, c.track_version) == (group[-1].track_id, group[-1].track_version) \
                and c.window_index == group[-1].window_index + 1:
            group.append(c)
        else:
            flush()
            group.append(c)
    flush()
    return out


@dataclass(frozen=True)
class ListenFlags:
    session_id: str
    start_wall: int
    shuffle: bool
    skipped: bool
    undone: bool
    first_press_ms: int | None


@dataclass(frozen=True)
class WindowEvidence:
    run: Run
    reached: int
    skipped: int
    undone: int
    attempts: int
    sessions_reached: int
    sessions_skipped: int
    days_skipped: int
    max_session_share: float
    shuffle_reached: int
    shuffle_skipped: int
    top_daypart: str | None
    top_daypart_share: float
    outside_reached: int
    outside_skipped: int
    median_first_press_ms: int | None
    last_skip_day: str | None
    changes: tuple[dict, ...] = ()

    @property
    def window_id(self) -> str:
        return self.run.window_id

    @property
    def skip_rate(self) -> float:
        return self.skipped / self.reached if self.reached else 0.0

    @property
    def undo_share(self) -> float:
        """Listens that undid part of the run, among listens that skipped or undid any of it."""
        return self.undone / self.attempts if self.attempts else 0.0

    @property
    def non_shuffle_reached(self) -> int:
        return self.reached - self.shuffle_reached

    @property
    def non_shuffle_skipped(self) -> int:
        return self.skipped - self.shuffle_skipped

    def to_request(self) -> dict:
        r = self.run
        return {
            "window_id": r.window_id, "track_id": r.track_id, "start": fmt_ms(r.start_ms), "end": fmt_ms(r.end_ms),
            "starts_at_track_start": r.first_window == 0, "track_listens": r.track_listens,
            "listens_reached": self.reached, "listens_skipped": self.skipped, "listens_undone": self.undone,
            "skip_rate": round(self.skip_rate, 3), "undo_share": round(self.undo_share, 3),
            "sessions_reached": self.sessions_reached, "sessions_skipped": self.sessions_skipped,
            "days_skipped": self.days_skipped, "max_session_share": round(self.max_session_share, 3),
            "shuffle_listens_reached": self.shuffle_reached, "shuffle_listens_skipped": self.shuffle_skipped,
            "top_daypart_of_skips": self.top_daypart, "top_daypart_share": round(self.top_daypart_share, 3),
            "listens_outside_top_daypart": self.outside_reached,
            "skips_outside_top_daypart": self.outside_skipped,
            "median_first_press": fmt_ms(self.median_first_press_ms) if self.median_first_press_ms is not None else None,
            "last_skip_day": self.last_skip_day, "changes": list(self.changes),
        }


def fmt_ms(ms: int) -> str:
    s = max(0, int(ms) // 1000)
    return f"{s // 60}:{s % 60:02d}"


def local_dt(wall_ms: int, utc_offset_minutes: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(wall_ms / 1000, dt.timezone(dt.timedelta(minutes=utc_offset_minutes)))


def local_day(wall_ms: int, utc_offset_minutes: int) -> str:
    return local_dt(wall_ms, utc_offset_minutes).date().isoformat()


def daypart(hour: int) -> str:
    return next(name for name, a, b in DAYPARTS if a <= hour < b)


class History:
    """Listens of every track version, interpreted once; heatmap and evidence come from them."""

    def __init__(self, events: Iterable[Event], cfg: InterpretConfig = DEFAULT_CONFIG,
                 until_ms: int | None = None):
        self.cfg = cfg
        evs = [e for e in events if e.is_playback and (until_ms is None or e.wall_time <= until_ms)]
        durations = resolve_durations(evs)
        self.listens: dict[VersionKey, list[Listen]] = {}
        self.heatmap = HeatmapBuilder(cfg)
        for session in group_sessions(evs).values():
            for listen in interpret_session(session, cfg, durations):
                self.heatmap.add_listen(listen)
                self.listens.setdefault(listen.key, []).append(listen)
        self._rows: dict[int, dict[int, tuple]] = {}

    def rows(self, listen: Listen) -> dict[int, tuple]:
        k = id(listen)
        if k not in self._rows:
            self._rows[k] = {r[0]: r for r in window_rows(listen, self.cfg)}
        return self._rows[k]

    def flags(self, run: Run) -> list[ListenFlags]:
        out = []
        span = range(run.first_window, run.last_window + 1)
        for listen in self.listens.get(run.key, ()):
            rows = self.rows(listen)
            hit = [rows[w] for w in span if w in rows]
            if not hit:
                continue
            first = None
            for b in listen.bursts:
                if any(s < run.end_ms and run.start_ms < e for s, e in b.presses):
                    first = b.presses[0][0]
                    break
            out.append(ListenFlags(listen.session_id, listen.start_wall, listen.shuffle,
                                   any(r[4] for r in hit), any(r[6] for r in hit), first))
        return out

    def evidence(self, run: Run, utc_offset_minutes: int = 0,
                 features: TrackFeatures | None = None) -> WindowEvidence:
        flags = self.flags(run)
        skips = [f for f in flags if f.skipped]
        per_session: dict[str, int] = {}
        for f in skips:
            per_session[f.session_id] = per_session.get(f.session_id, 0) + 1
        parts = [daypart(local_dt(f.start_wall, utc_offset_minutes).hour) for f in flags]
        skip_parts = [p for f, p in zip(flags, parts) if f.skipped]
        top, share = None, 0.0
        if skip_parts:
            counts = {p: skip_parts.count(p) for p in skip_parts}
            top = max(sorted(counts), key=lambda p: counts[p])
            share = counts[top] / len(skip_parts)
        outside = [f for f, p in zip(flags, parts) if p != top]
        presses = [f.first_press_ms for f in skips if f.first_press_ms is not None]
        feats = features.window_features(run.track_id, run.track_version) if features else None
        return WindowEvidence(
            run=run, reached=len(flags), skipped=len(skips),
            undone=sum(f.undone for f in flags), attempts=sum(f.skipped or f.undone for f in flags),
            sessions_reached=len({f.session_id for f in flags}), sessions_skipped=len(per_session),
            days_skipped=len({local_day(f.start_wall, utc_offset_minutes) for f in skips}),
            max_session_share=max(per_session.values()) / len(skips) if skips else 0.0,
            shuffle_reached=sum(f.shuffle for f in flags), shuffle_skipped=sum(f.shuffle for f in skips),
            top_daypart=top, top_daypart_share=share,
            outside_reached=len(outside), outside_skipped=sum(f.skipped for f in outside),
            median_first_press_ms=int(statistics.median(presses)) if presses else None,
            last_skip_day=local_day(max(f.start_wall for f in skips), utc_offset_minutes) if skips else None,
            changes=tuple(changes_at(feats, run.first_window)),
        )

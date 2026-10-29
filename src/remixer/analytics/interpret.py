"""Turn raw playback events into listens, skip bursts, undos, replays and signals.

Pure functions, no I/O. All thresholds live in ``InterpretConfig`` with documented defaults.

A *listen* is one uninterrupted visit to one ``track_version`` inside a session: it starts at
the first event for that version and ends at ``next``, ``previous``, ``track_end``, an event for a
different version (``switch``) or the end of the session (``abandoned``).

Rules (spec section 5):

- Skip burst: ``seek_fwd_5s`` presses each within ``burst_gap_ms`` of the previous press form one
  skip of N x 5 s.
- Undo: a ``seek_back_5s`` within ``undo_window_ms`` of the burst's last press (or of the previous
  undo press) cancels the burst's most recent uncancelled press. The cancelled audio counts as
  ``undone`` (mildly positive), never as skipped. This covers "the skipped part led into
  something good".
- Late return (``late_return_cancels_skip``): a later -5 s that lands in audio skipped earlier in
  the same listen also cancels that part of the skip.
- Replay: a -5 s that is not an undo, over audio already heard in this listen, is a positive
  signal for those windows.
- Next: early (``position <= early_next_fraction * duration`` or, with unknown duration,
  ``position <= early_next_ms``) is a track-level negative; near the end (within ``near_end_ms``
  or past ``near_end_fraction``) is no signal; in between is a weaker negative.
- Previous: past ``restart_threshold_ms`` it restarts the current track (positive for it);
  otherwise it returns to the previous track in the session (positive for that one).

Passive signals feed analytics only; nothing here prompts the user.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .events import SEEK_MS, Event, group_sessions
from .intervals import Interval, intersect, merge, subtract

VersionKey = tuple[str, str]


@dataclass(frozen=True)
class InterpretConfig:
    window_ms: int = 5000
    seek_ms: int = SEEK_MS
    burst_gap_ms: int = 2000            # "several +5 s presses within about 2 seconds"
    undo_window_ms: int = 6000          # "a -5 s soon after a +5 s"
    late_return_cancels_skip: bool = True
    coverage_fraction: float = 0.5      # share of a window that must be heard/skipped/... to count
    min_reach_ms: int = 500             # traversal needed for a window to count as reached
    last_press_credit: float = 0.75     # share of a burst's final net press counted as skipped
    restart_threshold_ms: int = 3000    # previous past this point restarts the current track
    early_next_fraction: float = 0.33
    early_next_ms: int = 30000          # used when the duration is unknown
    near_end_ms: int = 15000
    near_end_fraction: float = 0.9
    skip_weight: float = -1.0           # per skipped window
    undo_weight: float = 0.25           # per undone window: neutral to mildly positive
    replay_weight: float = 1.0          # per replayed window
    early_next_weight: float = -1.0
    mid_next_weight: float = -0.5
    previous_weight: float = 1.0
    restart_weight: float = 1.0


DEFAULT_CONFIG = InterpretConfig()


@dataclass
class SkipBurst:
    start_wall: int
    last_wall: int
    presses: list[Interval] = field(default_factory=list)
    undone: int = 0
    last_undo_wall: int | None = None

    @property
    def n_presses(self) -> int:
        return len(self.presses)

    @property
    def net_presses(self) -> int:
        return self.n_presses - self.undone

    @property
    def cancelled(self) -> bool:
        return self.undone >= self.n_presses

    @property
    def origin_ms(self) -> int:
        return self.presses[0][0]


@dataclass
class Listen:
    session_id: str
    track_id: str
    track_version: str
    source_kind: str
    index: int
    start_wall: int
    start_ms: int
    duration_ms: int | None
    shuffle: bool = False
    heard: list[Interval] = field(default_factory=list)
    bursts: list[SkipBurst] = field(default_factory=list)
    undone: list[Interval] = field(default_factory=list)
    replays: list[Interval] = field(default_factory=list)
    late_returns: int = 0
    end_wall: int = 0
    end_ms: int = 0
    end_reason: str = "abandoned"

    @property
    def key(self) -> VersionKey:
        return (self.track_id, self.track_version)

    @property
    def skipped(self) -> list[Interval]:
        """Net skipped audio: every press minus everything undone."""
        return subtract((p for b in self.bursts for p in b.presses), self.undone)

    @property
    def traversed(self) -> list[Interval]:
        """Audio the playhead went through, by ear or by seek: defines ``reached``."""
        return merge([*self.heard, *self.skipped, *self.undone])

    @property
    def reached_ms(self) -> int:
        t = self.traversed
        return t[-1][1] if t else self.start_ms


@dataclass(frozen=True)
class WindowFlags:
    index: int
    start_ms: int
    end_ms: int
    played: bool
    skipped: bool
    replayed: bool
    undone: bool


@dataclass(frozen=True)
class Signal:
    session_id: str
    track_id: str
    track_version: str
    source_kind: str
    kind: str        # skip | undo | replay | early_next | mid_next | previous | restart
    level: str       # window | track
    weight: float
    wall_time: int
    window_index: int | None = None
    shuffle: bool = False


@dataclass
class Interpretation:
    listens: list[Listen]
    signals: list[Signal]


def resolve_durations(events: Iterable[Event], known: Mapping[VersionKey, int] | None = None
                      ) -> dict[VersionKey, int]:
    """Explicit durations win, then ``client_info.duration_ms``, then the latest ``track_end``."""
    out: dict[VersionKey, int] = {}
    for e in events:
        hint = e.client_info.get("duration_ms") if e.client_info else None
        if isinstance(hint, (int, float)) and hint > 0:
            out[e.version_key] = int(hint)
        elif e.event_type == "track_end" and e.version_key not in out:
            out[e.version_key] = e.position_ms
        elif e.event_type == "track_end":
            out[e.version_key] = max(out[e.version_key], e.position_ms)
    if known:
        out.update(known)
    return out


def interpret_session(events: Sequence[Event], cfg: InterpretConfig = DEFAULT_CONFIG,
                      durations: Mapping[VersionKey, int] | None = None) -> list[Listen]:
    """Split one session's events (sorted by wall time) into listens.

    Without ``durations``, they are resolved from this session's own events.
    """
    if durations is None:
        durations = resolve_durations(events)
    listens: list[Listen] = []
    cur: Listen | None = None
    playing = False
    pos = 0
    burst: SkipBurst | None = None
    last_wall = 0

    def close(reason: str, at_ms: int, wall: int) -> None:
        cur.end_reason, cur.end_ms, cur.end_wall = reason, at_ms, wall
        cur.heard = merge(cur.heard)
        cur.undone = merge(cur.undone)
        cur.replays = merge(cur.replays)
        listens.append(cur)

    for e in events:
        if not e.is_playback:
            continue
        last_wall = e.wall_time
        if cur is not None and cur.key != e.version_key:
            close("switch", pos, e.wall_time)
            cur = None
        if cur is None:
            cur = Listen(
                session_id=e.session_id, track_id=e.track_id, track_version=e.track_version,
                source_kind=e.source_kind, index=len(listens), start_wall=e.wall_time,
                start_ms=e.position_ms, duration_ms=durations.get(e.version_key),
                shuffle=bool(e.client_info.get("shuffle")) if e.client_info else False,
            )
            playing, pos, burst = False, e.position_ms, None
        dur = cur.duration_ms
        p = min(e.position_ms, dur) if dur else e.position_ms
        if playing and p > pos:
            cur.heard.append((pos, p))
        t = e.event_type
        if t == "play":
            playing = True
        elif t == "pause":
            playing = False
        elif t == "seek_fwd_5s":
            to = min(p + cfg.seek_ms, dur) if dur else p + cfg.seek_ms
            if burst is not None and not burst.undone and e.wall_time - burst.last_wall <= cfg.burst_gap_ms:
                burst.presses.append((p, to))
                burst.last_wall = e.wall_time
            else:
                burst = SkipBurst(start_wall=e.wall_time, last_wall=e.wall_time, presses=[(p, to)])
                cur.bursts.append(burst)
            p = to
        elif t == "seek_back_5s":
            to = max(0, p - cfg.seek_ms)
            anchor = (burst.last_undo_wall or burst.last_wall) if burst else None
            if burst is not None and not burst.cancelled and e.wall_time - anchor <= cfg.undo_window_ms:
                cur.undone.append(burst.presses[burst.n_presses - 1 - burst.undone])
                burst.undone += 1
                burst.last_undo_wall = e.wall_time
            else:
                region = [(to, p)]
                if cfg.late_return_cancels_skip:
                    back = intersect(region, cur.skipped)
                    if back:
                        cur.undone.extend(back)
                        cur.late_returns += 1
                cur.replays.extend(intersect(region, merge(cur.heard)))
                burst = None
            p = to
        else:  # next, previous, track_end
            close(t, p, e.wall_time)
            cur = None
            continue
        pos = p
    if cur is not None:
        close("abandoned", pos, last_wall)
    return listens


def classify_windows(listen: Listen, cfg: InterpretConfig = DEFAULT_CONFIG) -> list[WindowFlags]:
    """Flags for every window this listen reached (heard, skipped over, or undone)."""
    return [WindowFlags(*row) for row in window_rows(listen, cfg)]


def window_rows(listen: Listen, cfg: InterpretConfig = DEFAULT_CONFIG
                ) -> Iterator[tuple[int, int, int, bool, bool, bool, bool]]:
    """``(index, start_ms, end_ms, played, skipped, replayed, undone)`` per reached window."""
    skipped = listen.skipped
    trav = merge([*listen.heard, *skipped, *listen.undone])
    if not trav:
        return
    if skipped and cfg.last_press_credit < 1.0:
        tails = []
        for b in listen.bursts:
            if b.net_presses:
                s, e = b.presses[b.net_presses - 1]
                tails.append((s + int(cfg.last_press_credit * (e - s)), e))
        skipped = subtract(skipped, tails)
    w_ms = cfg.window_ms
    n = (trav[-1][1] - 1) // w_ms + 1
    reach = bin_coverage(trav, w_ms, n)
    heard = bin_coverage(listen.heard, w_ms, n)
    skip = bin_coverage(skipped, w_ms, n) if skipped else None
    replay = bin_coverage(listen.replays, w_ms, n) if listen.replays else None
    undo = bin_coverage(listen.undone, w_ms, n) if listen.undone else None
    dur = listen.duration_ms
    frac, min_reach = cfg.coverage_fraction, cfg.min_reach_ms
    for w in range(trav[0][0] // w_ms, n):
        ws, we = w * w_ms, (w + 1) * w_ms
        if dur and we > dur:
            we = dur
        if we <= ws or reach[w] < min(min_reach, we - ws):
            continue
        need = frac * (we - ws)
        yield (w, ws, we, heard[w] >= need, skip is not None and skip[w] >= need,
               replay is not None and replay[w] >= need, undo is not None and undo[w] >= need)


def bin_coverage(intervals: Iterable[Interval], window_ms: int, n_windows: int) -> list[int]:
    """Milliseconds of ``intervals`` (disjoint) falling in each window ``0..n_windows-1``."""
    cov = [0] * n_windows
    for s, e in intervals:
        w = s // window_ms
        while s < e and w < n_windows:
            b = min(e, (w + 1) * window_ms)
            cov[w] += b - s
            s, w = b, w + 1
    return cov


def classify_next(position_ms: int, duration_ms: int | None, cfg: InterpretConfig = DEFAULT_CONFIG) -> str:
    """``early``, ``mid`` or ``near_end``."""
    if duration_ms:
        if duration_ms - position_ms <= cfg.near_end_ms or position_ms >= cfg.near_end_fraction * duration_ms:
            return "near_end"
        return "early" if position_ms <= cfg.early_next_fraction * duration_ms else "mid"
    return "early" if position_ms <= cfg.early_next_ms else "mid"


def listen_signals(listen: Listen, cfg: InterpretConfig = DEFAULT_CONFIG,
                   previous_listen: Listen | None = None) -> list[Signal]:
    def sig(kind, level, weight, wall, window=None, target=listen):
        return Signal(target.session_id, target.track_id, target.track_version, target.source_kind,
                      kind, level, weight, wall, window, listen.shuffle)

    out = []
    for f in classify_windows(listen, cfg):
        if f.skipped:
            out.append(sig("skip", "window", cfg.skip_weight, listen.end_wall, f.index))
        if f.undone:
            out.append(sig("undo", "window", cfg.undo_weight, listen.end_wall, f.index))
        if f.replayed:
            out.append(sig("replay", "window", cfg.replay_weight, listen.end_wall, f.index))
    if listen.end_reason == "next":
        cls = classify_next(listen.end_ms, listen.duration_ms, cfg)
        if cls == "early":
            out.append(sig("early_next", "track", cfg.early_next_weight, listen.end_wall))
        elif cls == "mid":
            out.append(sig("mid_next", "track", cfg.mid_next_weight, listen.end_wall))
    elif listen.end_reason == "previous":
        if listen.end_ms > cfg.restart_threshold_ms:
            out.append(sig("restart", "track", cfg.restart_weight, listen.end_wall))
        elif previous_listen is not None:
            out.append(sig("previous", "track", cfg.previous_weight, listen.end_wall, target=previous_listen))
    return out


def interpret(events: Iterable[Event], cfg: InterpretConfig = DEFAULT_CONFIG,
              durations: Mapping[VersionKey, int] | None = None) -> Interpretation:
    events = list(events)
    durs = resolve_durations(events, durations)
    listens: list[Listen] = []
    signals: list[Signal] = []
    for session in group_sessions(events).values():
        ls = interpret_session(session, cfg, durs)
        for i, listen in enumerate(ls):
            signals.extend(listen_signals(listen, cfg, ls[i - 1] if i else None))
        listens.extend(ls)
    return Interpretation(listens, signals)


def summarize_listen(listen: Listen) -> dict[str, Any]:
    return {
        "track_version": listen.track_version, "end_reason": listen.end_reason,
        "bursts": [(b.n_presses, b.net_presses) for b in listen.bursts],
        "skipped": listen.skipped, "undone": listen.undone, "replays": listen.replays,
    }

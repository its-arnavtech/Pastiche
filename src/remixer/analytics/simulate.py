"""Synthetic listening sessions with planted skip patterns, for detector tests and scale runs.

Every generated event carries ``client_info.synthetic = True`` so simulated rows never mix with
real taste data. Ground truth is the set of planted *disliked* windows; *teases* (skipped and then
undone: "the skipped part led into something good") and *loved* regions (replayed) must not be
flagged. Personas are the owner's listening modes, not different people.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Iterator, Mapping

from .events import SEEK_MS, Event

WINDOW_MS = 5000
T0_MS = 1_790_000_000_000  # 2026-09-21 UTC; any fixed epoch keeps runs reproducible


@dataclass(frozen=True)
class Persona:
    name: str
    skip_prob: float              # chance to skip a disliked region on reaching it
    reaction_ms: tuple[int, int]  # time heard inside a disliked region before the first press
    press_gap_ms: tuple[int, int]
    overshoot_prob: float         # one press too many, then an undo
    undo_delay_ms: tuple[int, int]
    anticipate_prob: float        # on repeat listens, press just before a known disliked region
    tease_skip_prob: float        # skip a tease region, then always undo
    replay_prob: float            # replay a loved region
    noise_skip_rate: float        # per window, a random lone +5 s
    noise_undo_prob: float
    early_next_prob: float
    abandon_prob: float
    pause_prob: float
    shuffle_prob: float


PERSONAS: dict[str, Persona] = {
    "attentive": Persona("attentive", 0.95, (300, 1800), (150, 700), 0.15, (700, 3000), 0.4,
                         0.6, 0.5, 0.005, 0.5, 0.04, 0.02, 0.10, 0.1),
    "impatient": Persona("impatient", 0.9, (200, 1200), (120, 500), 0.35, (500, 2500), 0.5,
                         0.8, 0.2, 0.02, 0.4, 0.15, 0.05, 0.05, 0.3),
    "lean_back": Persona("lean_back", 0.5, (800, 2400), (300, 900), 0.1, (900, 3500), 0.1,
                         0.3, 0.3, 0.003, 0.5, 0.03, 0.05, 0.15, 0.2),
    "shuffle_hopper": Persona("shuffle_hopper", 0.8, (200, 1500), (150, 600), 0.25, (600, 2500), 0.3,
                              0.7, 0.15, 0.01, 0.4, 0.35, 0.05, 0.05, 0.9),
}
DEFAULT_MIX: dict[str, float] = {"attentive": 0.35, "impatient": 0.25, "lean_back": 0.25, "shuffle_hopper": 0.15}

Region = tuple[int, int]  # [first_window, end_window)


@dataclass(frozen=True)
class TrackSpec:
    track_id: str
    track_version: str
    duration_ms: int
    source_kind: str = "source"
    disliked: tuple[Region, ...] = ()
    teases: tuple[Region, ...] = ()
    loved: tuple[Region, ...] = ()

    @property
    def key(self) -> tuple[str, str]:
        return (self.track_id, self.track_version)

    @property
    def n_windows(self) -> int:
        return math.ceil(self.duration_ms / WINDOW_MS)

    def windows(self, regions: tuple[Region, ...]) -> set[int]:
        return {w for a, b in regions for w in range(a, b)}


class Player:
    """Deterministic emitter with a virtual wall clock and playhead; mirrors the web player."""

    def __init__(self, session_id: str, t0: int = T0_MS, client_info: Mapping | None = None):
        self.session_id = session_id
        self.wall = t0
        self.client_info = dict(client_info or {})
        self.events: list[Event] = []
        self.track: TrackSpec | None = None
        self.pos = 0
        self.playing = False

    def _emit(self, event_type: str) -> None:
        t = self.track
        info = dict(self.client_info, duration_ms=t.duration_ms, seq=len(self.events))
        self.events.append(Event(
            f"{self.session_id}-{len(self.events)}", self.session_id, t.track_id, t.track_version,
            event_type, int(self.pos), int(self.wall), t.source_kind, info))

    def load(self, track: TrackSpec, at_ms: int = 0) -> "Player":
        self.track, self.pos, self.playing = track, at_ms, False
        return self

    def play(self) -> "Player":
        self._emit("play")
        self.playing = True
        return self

    def pause(self) -> "Player":
        self._emit("pause")
        self.playing = False
        return self

    def wait(self, ms: int) -> "Player":
        """Wall time passes; the playhead moves only while playing."""
        ms = int(ms)
        if self.playing:
            ms = min(ms, self.track.duration_ms - self.pos)
            self.pos += ms
        self.wall += ms
        return self

    def listen_to(self, pos_ms: int) -> "Player":
        return self.wait(max(0, int(pos_ms) - self.pos)) if self.playing else self

    def fwd(self) -> "Player":
        self._emit("seek_fwd_5s")
        self.pos = min(self.pos + SEEK_MS, self.track.duration_ms)
        return self

    def back(self) -> "Player":
        self._emit("seek_back_5s")
        self.pos = max(0, self.pos - SEEK_MS)
        return self

    def next(self) -> "Player":
        self._emit("next")
        self.playing = False
        return self

    def previous(self) -> "Player":
        self._emit("previous")
        self.playing = False
        return self

    def end(self) -> "Player":
        self.pos = self.track.duration_ms
        self._emit("track_end")
        self.playing = False
        return self

    @property
    def at_end(self) -> bool:
        return self.pos >= self.track.duration_ms


# ------------------------------------------------------------------ library

def make_library(n_tracks: int, rng: random.Random, planted_fraction: float = 0.45,
                 generated_fraction: float = 0.5, rerender_fraction: float = 0.1) -> list[TrackSpec]:
    """Tracks with non-overlapping planted regions, separated by at least three windows.

    A ``rerender_fraction`` of tracks with dislikes also get a ``v2`` with the dislike removed, as a
    re-rendered recipe would: its heatmap must start clean.
    """
    lib: list[TrackSpec] = []
    for i in range(n_tracks):
        dur = rng.randrange(120_000, 300_000, 500)
        n_win = math.ceil(dur / WINDOW_MS)
        free = list(range(3, n_win - 5))
        regions: dict[str, list[Region]] = {"disliked": [], "teases": [], "loved": []}

        def place(kind: str, length: int) -> None:
            for _ in range(20):
                if not free:
                    return
                start = rng.choice(free)
                span = range(start - 3, start + length + 3)
                if all(w in free for w in span):
                    regions[kind].append((start, start + length))
                    for w in span:
                        free.remove(w)
                    return

        if rng.random() < planted_fraction:
            for _ in range(rng.choice((1, 1, 2))):
                place("disliked", rng.choice((1, 1, 2, 2, 3, 4)))
        if rng.random() < 0.3:
            place("teases", rng.choice((1, 2)))
        if rng.random() < 0.3:
            place("loved", rng.choice((1, 2)))
        kind = "generated" if rng.random() < generated_fraction else "source"
        t = TrackSpec(f"trk{i:05d}", "v1", dur, kind, tuple(regions["disliked"]),
                      tuple(regions["teases"]), tuple(regions["loved"]))
        lib.append(t)
        if t.disliked and rng.random() < rerender_fraction:
            lib.append(TrackSpec(t.track_id, "v2", dur, kind, (), t.teases, t.loved))
    return lib


# ------------------------------------------------------------------ listening

def _u(rng: random.Random, lo_hi: tuple[int, int]) -> int:
    return rng.randint(*lo_hi)


def simulate_listen(p: Player, track: TrackSpec, persona: Persona, rng: random.Random,
                    repeat: bool, can_abandon: bool = True) -> str:
    """Emit one listen. Returns ``ended``, ``next`` or ``abandoned`` (the session stops)."""
    dur = track.duration_ms
    p.load(track).play()
    stop_at, stop_kind = None, None
    r = rng.random()
    if r < persona.early_next_prob:
        stop_at, stop_kind = rng.randint(1500, max(2000, min(40_000, int(0.3 * dur)))), "next"
    elif can_abandon and r < persona.early_next_prob + persona.abandon_prob:
        stop_at, stop_kind = rng.randint(int(0.05 * dur), int(0.95 * dur)), "abandon"
    pause_at = rng.randint(int(0.1 * dur), int(0.9 * dur)) if rng.random() < persona.pause_prob else None

    planted = track.windows(track.disliked) | track.windows(track.teases) | track.windows(track.loved)
    actions: list[tuple[int, str, Region | None]] = []
    actions += [(a * WINDOW_MS, "dislike", (a, b)) for a, b in track.disliked]
    actions += [(a * WINDOW_MS, "tease", (a, b)) for a, b in track.teases]
    actions += [(b * WINDOW_MS, "love", (a, b)) for a, b in track.loved]
    actions += [(w * WINDOW_MS + rng.randint(0, WINDOW_MS - 1), "noise", None)
                for w in range(track.n_windows) if w not in planted and rng.random() < persona.noise_skip_rate]
    actions.sort(key=lambda a: a[0])

    def stop() -> str:
        p.listen_to(stop_at)
        if stop_kind == "next":
            p.next()
            return "next"
        if rng.random() < 0.5:
            p.pause()
        return "abandoned"

    for at, kind, region in actions:
        if at < p.pos:
            continue
        if stop_at is not None and stop_at <= at:
            return stop()
        if pause_at is not None and pause_at <= at:
            p.listen_to(pause_at).pause().wait(rng.randint(3000, 90_000)).play()
            pause_at = None
        if kind == "dislike":
            if rng.random() >= persona.skip_prob:
                continue
            a, b = region
            if repeat and rng.random() < persona.anticipate_prob:
                p.listen_to(max(p.pos, a * WINDOW_MS - rng.randint(200, 1500)))
            else:
                p.listen_to(a * WINDOW_MS + _u(rng, persona.reaction_ms))
            n = max(1, math.ceil((b * WINDOW_MS - p.pos) / SEEK_MS))
            for i in range(n):
                if i:
                    p.wait(_u(rng, persona.press_gap_ms))
                p.fwd()
            if rng.random() < persona.overshoot_prob and not p.at_end:
                p.wait(_u(rng, persona.press_gap_ms)).fwd()
                p.wait(_u(rng, persona.undo_delay_ms)).back()
        elif kind == "tease":
            if rng.random() >= persona.tease_skip_prob:
                continue
            a, b = region
            p.listen_to(a * WINDOW_MS + _u(rng, persona.reaction_ms))
            n = max(1, math.ceil((b * WINDOW_MS - p.pos) / SEEK_MS))
            for i in range(n):
                if i:
                    p.wait(_u(rng, persona.press_gap_ms))
                p.fwd()
            p.wait(_u(rng, persona.undo_delay_ms))
            for _ in range(n):
                p.back().wait(_u(rng, persona.press_gap_ms))
        elif kind == "love":
            if rng.random() >= persona.replay_prob:
                continue
            p.listen_to(at + rng.randint(300, 2000))
            for _ in range(rng.choice((1, 1, 2))):
                p.back().wait(_u(rng, persona.press_gap_ms))
        else:
            p.listen_to(at).fwd()
            if rng.random() < persona.noise_undo_prob:
                p.wait(_u(rng, persona.undo_delay_ms)).back()
        if p.at_end:
            p.end()
            return "ended"
    if stop_at is not None and stop_at > p.pos:
        return stop()
    p.listen_to(dur)
    p.end()
    return "ended"


@dataclass
class Simulation:
    library: list[TrackSpec]
    events: list[Event] = field(default_factory=list)
    listens: dict[tuple[str, str], int] = field(default_factory=dict)

    def truth(self, min_listens: int = 0) -> set[tuple[str, str, int]]:
        return {(t.track_id, t.track_version, w) for t in self.library
                if self.listens.get(t.key, 0) >= min_listens for w in t.windows(t.disliked)}

    def tease_windows(self) -> set[tuple[str, str, int]]:
        return {(t.track_id, t.track_version, w) for t in self.library for w in t.windows(t.teases)}

    def loved_windows(self) -> set[tuple[str, str, int]]:
        return {(t.track_id, t.track_version, w) for t in self.library for w in t.windows(t.loved)}


def iter_sessions(library: list[TrackSpec], n_sessions: int, seed: int,
                  mix: Mapping[str, float] = DEFAULT_MIX, tracks_per_session: tuple[int, int] = (4, 14),
                  listens: dict | None = None) -> Iterator[list[Event]]:
    rng = random.Random(seed)
    names = list(mix)
    weights = [mix[n] for n in names]
    t = T0_MS
    for s in range(n_sessions):
        persona = PERSONAS[rng.choices(names, weights)[0]]
        shuffle = rng.random() < persona.shuffle_prob
        k = rng.randint(*tracks_per_session)
        if shuffle:
            order = rng.sample(library, min(k, len(library)))
        else:
            start = rng.randrange(len(library))
            order = [library[(start + i) % len(library)] for i in range(k)]
        sid = f"sim{seed}-{s:07d}"
        p = Player(sid, t, {"synthetic": True, "persona": persona.name, "shuffle": shuffle})
        for track in order:
            seen = listens.get(track.key, 0) if listens is not None else 0
            outcome = simulate_listen(p, track, persona, rng, repeat=seen > 0)
            if listens is not None:
                listens[track.key] = seen + 1
            if outcome == "abandoned":
                break
            p.wait(rng.randint(0, 1500))
        yield p.events
        t = p.wall + rng.randint(60_000, 6 * 3_600_000)


def simulate(n_tracks: int = 40, n_sessions: int = 400, seed: int = 0,
             mix: Mapping[str, float] = DEFAULT_MIX, **library_kw) -> Simulation:
    rng = random.Random(seed)
    sim = Simulation(make_library(n_tracks, rng, **library_kw))
    for events in iter_sessions(sim.library, n_sessions, seed + 1, mix, listens=sim.listens):
        sim.events.extend(events)
    return sim


def score(candidates, sim: Simulation, min_listens: int = 3) -> dict:
    """Precision and recall of detected windows against the planted dislikes."""
    found = {(c.track_id, c.track_version, c.window_index) for c in candidates}
    truth = sim.truth(min_listens)
    tp = len(found & truth)
    return {
        "tp": tp, "fp": len(found - truth), "fn": len(truth - found),
        "precision": tp / len(found) if found else 1.0,
        "recall": tp / len(truth) if truth else 1.0,
        "flagged_teases": len(found & sim.tease_windows()),
        "flagged_loved": len(found & sim.loved_windows()),
    }

"""A synthetic listening history with planted real dislikes and planted confounds.

All events carry ``client_info.synthetic = True``. They are built with the T-014 simulator's
``Player``, so they go through the same interpretation as real events.

Track kinds:

- ``dislike``: a region skipped in about 90% of listens, in any session, mode or time of day (truth).
- ``sparse``: a real dislike heard only twice, which the 3-listen rule must hold back.
- ``intro``: windows from 0:00 skipped right after the track starts.
- ``shuffle``: skipped only in shuffle sessions; played through in ordinary sessions.
- ``time_of_day``: skipped only in night sessions (mood); played through by day.
- ``undo``: skipped, but about 30% of the skips are undone (the user went back to it).
- ``few_listens``: four skipping listens, but only from two sessions.
- ``one_off``: a binge session that skipped it four times; played through elsewhere.
- ``plain``: nothing planted, only rare stray skips.
"""
from __future__ import annotations

import datetime as dt
import math
import random
from dataclasses import dataclass, field
from typing import Iterable

from remixer.analytics.events import Event
from remixer.analytics.simulate import WINDOW_MS, Player, TrackSpec

from .evidence import StaticFeatures, WindowFeatures

CONFOUNDS = ("intro", "shuffle", "time_of_day", "undo", "few_listens", "one_off")
KINDS = ("dislike", "sparse", "plain") + CONFOUNDS


@dataclass(frozen=True)
class Plant:
    track_id: str
    kind: str
    first_window: int
    end_window: int    # exclusive

    @property
    def start_ms(self) -> int:
        return self.first_window * WINDOW_MS

    @property
    def end_ms(self) -> int:
        return self.end_window * WINDOW_MS

    def overlaps(self, start_ms: int, end_ms: int) -> bool:
        return start_ms < self.end_ms and self.start_ms < end_ms


@dataclass(frozen=True)
class Session:
    index: int
    start_ms: int
    shuffle: bool
    night: bool


@dataclass
class ConfoundWorld:
    tracks: dict[str, TrackSpec]
    plants: dict[str, Plant]
    sessions: list[Session]
    events: list[Event]
    features: StaticFeatures
    start_ms: int
    days: int
    utc_offset_minutes: int
    listens: dict[str, int] = field(default_factory=dict)

    def night_ends(self) -> list[int]:
        """``now_ms`` for each nightly run: 03:30 local on each day after the first."""
        return [self.start_ms + d * 86_400_000 + int(3.5 * 3_600_000) for d in range(1, self.days + 2)]

    def truth(self) -> list[Plant]:
        return [p for p in self.plants.values() if p.kind == "dislike"]


def _local_midnight(day: dt.date, utc_offset_minutes: int) -> int:
    epoch = dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp() * 1000
    return int(epoch) - utc_offset_minutes * 60_000


def _sessions(rng: random.Random, start_ms: int, days: int) -> list[Session]:
    out = []
    for d in range(days):
        base = start_ms + d * 86_400_000
        hours = sorted(rng.sample(range(7, 22), 3))
        if rng.random() < 0.6:
            hours = [rng.randint(0, 4)] + hours
        for h in hours:
            at = base + h * 3_600_000 + rng.randint(0, 40) * 60_000
            out.append(Session(len(out), at, rng.random() < 0.3, h < 6))
    return out


def _features(rng: random.Random, track: TrackSpec, plant: Plant | None) -> list[WindowFeatures]:
    n = track.n_windows
    vocals_from = rng.randint(2, 6)
    out = []
    for w in range(n):
        stems = {"drums", "bass", "other"} | ({"vocals"} if w >= vocals_from else set())
        loud = -14.0 + rng.uniform(-0.8, 0.8)
        section = ("intro", "verse", "chorus", "verse", "bridge", "chorus", "outro")[min(6, w // 6)]
        if plant and plant.kind == "dislike" and plant.first_window <= w < plant.end_window:
            if plant.first_window % 2:
                stems = stems | {"lead synths"}
            else:
                loud += 6.0
        out.append(WindowFeatures(w, round(loud, 2), 120.0, section, frozenset(stems)))
    return out


def _skip_region(p: Player, rng: random.Random, a: int, b: int, at_start: bool = False) -> None:
    p.listen_to(a * WINDOW_MS + (rng.randint(200, 1500) if at_start else rng.randint(300, 1800)))
    n = max(1, math.ceil((b * WINDOW_MS - p.pos) / 5000))
    for i in range(n):
        if i:
            p.wait(rng.randint(150, 700))
        p.fwd()


def _listen(p: Player, track: TrackSpec, plant: Plant | None, rng: random.Random, skip: bool,
            undo_prob: float = 0.0) -> None:
    p.load(track).play()
    planted = set(range(plant.first_window, plant.end_window)) if plant else set()
    noise = [w for w in range(track.n_windows) if w not in planted and w > 1 and rng.random() < 0.005]
    actions = sorted([(w * WINDOW_MS, "noise") for w in noise]
                     + ([(plant.start_ms, "skip")] if plant and skip else []))
    early = rng.randint(30_000, track.duration_ms - 5000) if rng.random() < 0.05 else None
    for at, kind in actions:
        if at < p.pos:
            continue
        if early is not None and early <= at:
            break
        if kind == "noise":
            p.listen_to(at + rng.randint(0, 4000)).fwd()
            continue
        presses_from = len(p.events)
        _skip_region(p, rng, plant.first_window, plant.end_window, at_start=plant.first_window == 0)
        n = sum(1 for e in p.events[presses_from:] if e.event_type == "seek_fwd_5s")
        if rng.random() < undo_prob:
            p.wait(rng.randint(700, 2500))
            for _ in range(n):
                p.back().wait(rng.randint(150, 600))
        elif rng.random() < 0.2 and not p.at_end:
            p.wait(rng.randint(150, 700)).fwd()
            p.wait(rng.randint(700, 2500)).back()
        if p.at_end:
            p.end()
            return
    if early is not None and early > p.pos:
        p.listen_to(early).next()
        return
    p.listen_to(track.duration_ms)
    p.end()


def _pick(rng: random.Random, pool: list[Session], k: int, taken: set[int] = frozenset()) -> list[Session]:
    pool = [s for s in pool if s.index not in taken]
    return rng.sample(pool, min(k, len(pool)))


def confound_world(seed: int = 0, days: int = 28, n_dislike: int = 24, n_per_confound: int = 8,
                   n_plain: int = 16, n_sparse: int = 4, utc_offset_minutes: int = -300,
                   start: dt.date = dt.date(2026, 9, 21)) -> ConfoundWorld:
    rng = random.Random(seed)
    start_ms = _local_midnight(start, utc_offset_minutes)
    sessions = _sessions(rng, start_ms, days)
    day_s = [s for s in sessions if not s.night]
    night_s = [s for s in sessions if s.night]
    ordinary = [s for s in sessions if not s.shuffle]
    shuffled = [s for s in sessions if s.shuffle]
    kinds = (["dislike"] * n_dislike + ["sparse"] * n_sparse + ["plain"] * n_plain
             + [k for k in CONFOUNDS for _ in range(n_per_confound)])
    tracks: dict[str, TrackSpec] = {}
    plants: dict[str, Plant] = {}
    feats: dict = {}
    plan: dict[int, list[tuple[str, bool, float]]] = {}   # session index -> [(track_id, skip, undo_prob)]

    def assign(tid: str, picks: Iterable[Session], skip, undo: float = 0.0, repeat: int = 1):
        for s in picks:
            for _ in range(repeat):
                plan.setdefault(s.index, []).append((tid, skip(s), undo))

    for i, kind in enumerate(kinds):
        tid = f"{kind}-{i:03d}"
        dur = rng.randrange(120_000, 240_000, 500)
        track = TrackSpec(tid, "v1", dur, rng.choice(("source", "generated")))
        n_win = track.n_windows
        if kind == "plain":
            plant = None
        elif kind == "intro":
            plant = Plant(tid, kind, 0, rng.randint(2, 4))
        else:
            a = rng.randint(4, n_win - 9)
            plant = Plant(tid, kind, a, a + rng.choice((1, 2, 2, 3)))
        tracks[tid] = track
        if plant:
            plants[tid] = plant
        feats[track.key] = _features(rng, track, plant)
        p90 = lambda s: rng.random() < 0.9  # noqa: E731
        if kind in ("dislike", "intro"):
            assign(tid, _pick(rng, sessions, rng.randint(6, 10)), p90)
        elif kind == "sparse":
            assign(tid, _pick(rng, sessions, 2), lambda s: True)
        elif kind == "plain":
            assign(tid, _pick(rng, sessions, rng.randint(6, 10)), lambda s: False)
        elif kind == "undo":
            assign(tid, _pick(rng, sessions, rng.randint(7, 10)), lambda s: rng.random() < 0.95, undo=0.3)
        elif kind == "shuffle":
            sh = _pick(rng, shuffled, rng.randint(6, 8))
            assign(tid, sh, p90)
            assign(tid, _pick(rng, ordinary, rng.randint(2, 3), {s.index for s in sh}), lambda s: False)
        elif kind == "time_of_day":
            assign(tid, _pick(rng, night_s, rng.randint(5, 7)), lambda s: rng.random() < 0.95)
            assign(tid, _pick(rng, day_s, rng.randint(3, 4)), lambda s: False)
        elif kind == "few_listens":
            assign(tid, _pick(rng, sessions, 2), lambda s: True, repeat=2)
        elif kind == "one_off":
            binge = _pick(rng, sessions, 1)
            assign(tid, binge, lambda s: True, repeat=4)
            assign(tid, _pick(rng, sessions, rng.randint(2, 3), {binge[0].index}), lambda s: False)

    events: list[Event] = []
    listens: dict[str, int] = {}
    for s in sessions:
        items = plan.get(s.index, [])
        if not items:
            continue
        rng.shuffle(items)
        p = Player(f"cw{seed}-{s.index:05d}", s.start_ms, {"synthetic": True, "shuffle": s.shuffle})
        for tid, skip, undo in items:
            _listen(p, tracks[tid], plants.get(tid), rng, skip, undo)
            listens[tid] = listens.get(tid, 0) + 1
            p.wait(rng.randint(0, 1500))
        events.extend(p.events)
    return ConfoundWorld(tracks, plants, sessions, events, StaticFeatures(feats), start_ms, days,
                         utc_offset_minutes, listens)


def score(records: Iterable, world: ConfoundWorld) -> dict:
    """Precision and recall of surfaced insights (every proposed record) against planted dislikes."""
    recs = list(records)
    by_kind: dict[str, int] = {}
    tp_records = 0
    hit: set[str] = set()
    for r in recs:
        plant = world.plants.get(r.track_id)
        kind = plant.kind if plant and plant.overlaps(r.start_ms, r.end_ms) else "unplanted"
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if kind == "dislike":
            tp_records += 1
            hit.add(r.track_id)
    truth = world.truth()
    return {
        "surfaced": len(recs), "true_positive": tp_records, "false_positive": len(recs) - tp_records,
        "precision": tp_records / len(recs) if recs else 1.0,
        "recall": len(hit) / len(truth) if truth else 1.0,
        "dislikes": len(truth), "dislikes_found": len(hit), "surfaced_by_kind": dict(sorted(by_kind.items())),
    }

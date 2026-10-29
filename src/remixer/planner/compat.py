"""Compatibility of a stem with a section target (key, tempo, beat grid, energy, role).

Defaults are in ``CompatConfig`` and decision 0019. A stem is compatible with a target when:

- **meter** (beat grid): same beats per bar. Source ranges always start on a source downbeat, so
  bars line up after stretching.
- **tempo**: some multiplier ``m`` in (1, 0.5, 2) (half/double time if allowed) gives a stretch
  ``target_bpm / (bpm x m)`` within ``max_stretch`` (8 percent). Native tempo wins ties.
- **key** (not for drums): some pitch shift ``s`` with ``|s| <= max_shift`` puts the stem within
  ``max_camelot`` steps of the target on the Camelot wheel (same key, adjacent number, or the
  relative major/minor). Among valid shifts the lowest cost ``camelot x key_step_cost +
  |s| x shift_cost`` wins, then the smaller ``|s|``, then the upward shift.
- **energy**: ``|energy - target| <= energy_tolerance``.

The fit is a product of per-rule fits in (0, 1]: key ``1 - cost``, tempo
``1 - 0.5 x |stretch - 1| / max_stretch`` (times ``half_double_penalty`` off native tempo),
energy ``1 - 0.5 x |diff| / tolerance``.

``fit()`` is the scalar reference used by brute-force tests; ``CandidateIndex`` is the vectorized
path the planner uses. Both must agree.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .catalog import StemMeta
from .model import ROLES, parse_key

KEY_AGNOSTIC_ROLES = frozenset({"drums"})


@dataclass(frozen=True)
class CompatConfig:
    max_stretch: float = 0.08
    allow_half_double: bool = True
    half_double_penalty: float = 0.9
    max_shift: int = 2
    max_camelot: int = 1
    key_step_cost: float = 0.15
    shift_cost: float = 0.1
    energy_tolerance: float = 0.35


DEFAULT_COMPAT = CompatConfig()


@dataclass(frozen=True)
class Target:
    tempo_bpm: float
    key: str
    meter: int
    energy: float


@dataclass(frozen=True)
class Fit:
    score: float
    shift: int
    stretch: float
    multiplier: float


def key_id(key: str) -> int:
    pc, minor = parse_key(key)
    return pc + 12 * minor


def camelot(kid: int) -> tuple[int, bool]:
    """(number 1..12, is_major). C major = 8B, A minor = 8A."""
    pc, minor = kid % 12, kid >= 12
    major_pc = (pc + 3) % 12 if minor else pc
    return ((7 * major_pc) % 12 + 7) % 12 + 1, not minor


def camelot_distance(a: int, b: int) -> int:
    (na, ma), (nb, mb) = camelot(a), camelot(b)
    d = abs(na - nb)
    return min(d, 12 - d) + (ma != mb)


def shifted(kid: int, s: int) -> int:
    return (kid % 12 + s) % 12 + 12 * (kid >= 12)


def best_shift(source: int, target: int, cfg: CompatConfig) -> tuple[int, float] | None:
    """(shift, key fit) or None when no allowed shift reaches the target neighbourhood."""
    best = None
    for s in range(-cfg.max_shift, cfg.max_shift + 1):
        d = camelot_distance(shifted(source, s), target)
        if d > cfg.max_camelot:
            continue
        cost = d * cfg.key_step_cost + abs(s) * cfg.shift_cost
        rank = (round(cost, 9), abs(s), -s)
        if best is None or rank < best[0]:
            best = (rank, s, 1.0 - cost)
    return None if best is None else (best[1], best[2])


def _key_table(cfg: CompatConfig) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ok = np.zeros((24, 24), bool)
    shift = np.zeros((24, 24), np.int8)
    fit = np.zeros((24, 24), np.float64)
    for t in range(24):
        for s in range(24):
            r = best_shift(s, t, cfg)
            if r is not None:
                ok[t, s], shift[t, s], fit[t, s] = True, r[0], r[1]
    return ok, shift, fit


def multipliers(cfg: CompatConfig) -> tuple[float, ...]:
    return (1.0, 0.5, 2.0) if cfg.allow_half_double else (1.0,)


def tempo_fit(bpm: float, target_bpm: float, cfg: CompatConfig) -> tuple[float, float, float] | None:
    """(fit, stretch, multiplier) or None."""
    for m in multipliers(cfg):  # windows for different m never overlap, so at most one matches
        stretch = target_bpm / (bpm * m)
        if abs(stretch - 1.0) <= cfg.max_stretch + 1e-12:
            f = 1.0 - 0.5 * abs(stretch - 1.0) / cfg.max_stretch
            return f * (1.0 if m == 1.0 else cfg.half_double_penalty), stretch, m
    return None


def fit(stem: StemMeta, target: Target, cfg: CompatConfig = DEFAULT_COMPAT) -> Fit | None:
    """Scalar reference: the compatibility of one stem with one section target."""
    if stem.meter != target.meter:
        return None
    t = tempo_fit(stem.bpm, target.tempo_bpm, cfg)
    if t is None:
        return None
    diff = abs(stem.energy - target.energy)
    if diff > cfg.energy_tolerance + 1e-12:
        return None
    if stem.role in KEY_AGNOSTIC_ROLES:
        shift, kf = 0, 1.0
    else:
        k = best_shift(key_id(stem.key), key_id(target.key), cfg)
        if k is None:
            return None
        shift, kf = k
    return Fit(kf * t[0] * (1.0 - 0.5 * diff / cfg.energy_tolerance), shift, t[1], t[2])


def bar_ms(bpm: float, meter: int) -> float:
    return meter * 60_000.0 / bpm


def section_length_ms(target: Target, bars: int) -> int:
    return int(round(bars * bar_ms(target.tempo_bpm, target.meter)))


def source_length_ms(dst_len_ms: int, stretch: float) -> int:
    return int(round(dst_len_ms * stretch))


def position_at(stem: StemMeta, k: int) -> int:
    return int(round(stem.downbeat_ms + k * bar_ms(stem.bpm, stem.meter)))


def position_count(stem: StemMeta, src_len_ms: int) -> int:
    """How many downbeat-grid starts fit ``src_len_ms`` (they are ``position_at(stem, 0..n-1)``)."""
    room = stem.duration_ms - stem.downbeat_ms - src_len_ms
    if room < 0:
        return 0
    n = int(room // bar_ms(stem.bpm, stem.meter)) + 1
    while n and position_at(stem, n - 1) + src_len_ms > stem.duration_ms:
        n -= 1
    return n


def positions(stem: StemMeta, src_len_ms: int) -> list[int]:
    """Source start times on the stem's downbeat grid where ``src_len_ms`` fits."""
    return [position_at(stem, k) for k in range(position_count(stem, src_len_ms))]


class CandidateIndex:
    """Columnar view of the catalog for vectorized compatibility queries.

    Stems are sorted by ``stem_id`` so results never depend on catalog order. Per (role, meter)
    the stems are sorted by bpm; a query takes one bpm slice per tempo multiplier.
    """

    def __init__(self, stems: Sequence[StemMeta], cfg: CompatConfig = DEFAULT_COMPAT):
        self.cfg = cfg
        self.stems = sorted(stems, key=lambda s: s.stem_id)
        self.ids = [s.stem_id for s in self.stems]
        self.pos = {sid: i for i, sid in enumerate(self.ids)}
        n = len(self.stems)
        self.role = np.array([ROLES.index(s.role) for s in self.stems], np.int8)
        self.bpm = np.array([s.bpm for s in self.stems], np.float64)
        self.key = np.array([key_id(s.key) for s in self.stems], np.int8)
        self.meter = np.array([s.meter for s in self.stems], np.int16)
        self.energy = np.array([s.energy for s in self.stems], np.float64)
        self.songs = sorted({s.song_id for s in self.stems})
        song_pos = {sid: i for i, sid in enumerate(self.songs)}
        self.song = np.array([song_pos[s.song_id] for s in self.stems], np.int64)
        self.song_pos = song_pos
        self.emb = (np.stack([s.embedding for s in self.stems]).astype(np.float32)
                    if n else np.zeros((0, 1), np.float32))
        self.key_ok, self.key_shift, self.key_fit = _key_table(cfg)
        self.buckets: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
        for r in range(len(ROLES)):
            for m in np.unique(self.meter):
                idx = np.nonzero((self.role == r) & (self.meter == m))[0]
                idx = idx[np.argsort(self.bpm[idx], kind="stable")]
                self.buckets[(r, int(m))] = (idx, self.bpm[idx])

    def __len__(self) -> int:
        return len(self.stems)

    def query(self, role: str, target: Target) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Compatible stems for (role, target): (indices, fit, shift, stretch, multiplier), in bucket order."""
        cfg = self.cfg
        r = ROLES.index(role)
        bucket = self.buckets.get((r, target.meter))
        empty = (np.zeros(0, np.int64), np.zeros(0), np.zeros(0, np.int8), np.zeros(0), np.zeros(0))
        if bucket is None:
            return empty
        idx_sorted, bpm_sorted = bucket
        parts = []
        lo_s, hi_s = 1.0 - cfg.max_stretch - 1e-12, 1.0 + cfg.max_stretch + 1e-12
        for m in multipliers(cfg):
            # stretch = t / (b m) in [lo_s, hi_s]  <=>  b in [t / (m hi_s), t / (m lo_s)]
            lo = bisect.bisect_left(bpm_sorted, target.tempo_bpm / (m * hi_s))
            hi = bisect.bisect_right(bpm_sorted, target.tempo_bpm / (m * lo_s))
            if hi > lo:
                parts.append((idx_sorted[lo:hi], m))
        if not parts:
            return empty
        idx = np.concatenate([p[0] for p in parts])
        mult = np.concatenate([np.full(len(p[0]), p[1]) for p in parts])
        stretch = target.tempo_bpm / (self.bpm[idx] * mult)
        ok = np.abs(stretch - 1.0) <= cfg.max_stretch + 1e-12
        diff = np.abs(self.energy[idx] - target.energy)
        ok &= diff <= cfg.energy_tolerance + 1e-12
        if role in KEY_AGNOSTIC_ROLES:
            kfit = np.ones(len(idx))
            shift = np.zeros(len(idx), np.int8)
        else:
            t = key_id(target.key)
            src = self.key[idx]
            ok &= self.key_ok[t, src]
            kfit = self.key_fit[t, src]
            shift = self.key_shift[t, src]
        tfit = (1.0 - 0.5 * np.abs(stretch - 1.0) / cfg.max_stretch) * np.where(mult == 1.0, 1.0, cfg.half_double_penalty)
        score = kfit * tfit * (1.0 - 0.5 * diff / cfg.energy_tolerance)
        keep = np.nonzero(ok)[0]
        return idx[keep], score[keep], shift[keep], stretch[keep], mult[keep]

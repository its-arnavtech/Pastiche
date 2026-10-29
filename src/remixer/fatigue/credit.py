"""Credit assignment: spread a rating on a generated track across the stems that were audible.

Weights are loudness shares: integrated loudness (LUFS) converted to linear power, times the
time the stem is audible inside the rated span (whole track, or one window when the signal is
window-specific). Stems quieter than ``audible_floor_lufs`` get no credit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class StemUse:
    """One placement of a stem in a recipe (the subset of the core recipe this module needs)."""
    stem_id: str
    source_id: str
    start_ms: int
    end_ms: int
    loudness_lufs: float


Recipe = Sequence[StemUse]


@dataclass(frozen=True)
class CreditConfig:
    audible_floor_lufs: float = -50.0


DEFAULT_CREDIT = CreditConfig()


def loudness_shares(recipe: Recipe, window: tuple[int, int] | None = None,
                    cfg: CreditConfig = DEFAULT_CREDIT) -> dict[str, float]:
    """Stem id -> share in [0, 1], summing to 1 over audible stems (empty if nothing audible)."""
    raw: dict[str, float] = {}
    for u in recipe:
        if u.loudness_lufs < cfg.audible_floor_lufs:
            continue
        lo, hi = (u.start_ms, u.end_ms) if window is None else (max(u.start_ms, window[0]), min(u.end_ms, window[1]))
        if hi <= lo:
            continue
        raw[u.stem_id] = raw.get(u.stem_id, 0.0) + 10 ** (u.loudness_lufs / 10) * (hi - lo)
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()} if total > 0 else {}


def assign_credit(value: float, recipe: Recipe, window: tuple[int, int] | None = None,
                  cfg: CreditConfig = DEFAULT_CREDIT) -> dict[str, float]:
    """Distribute ``value`` (for example +1 / -1) across audible stems by loudness share."""
    return {k: value * s for k, s in loudness_shares(recipe, window, cfg).items()}


def sources_of(recipe: Recipe) -> Mapping[str, str]:
    return {u.stem_id: u.source_id for u in recipe}

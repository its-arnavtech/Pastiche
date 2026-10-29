"""Selection weight ``taste_score x (1 - fatigue) x novelty_bonus`` and the per-source batch cap.

- ``fatigue`` combines the stem's and its source song's decayed fatigue: ``1 - (1-f_stem)(1-f_src)``.
- ``novelty_bonus = 1 + novelty_max / (1 + exposures)``: unheard stems get up to ``1 + novelty_max``.
- Permanently disliked stems or sources weigh 0.
- Confirmed insights (and only confirmed ones) zero out candidates whose source time range
  overlaps the insight. Unconfirmed insights are ignored.
- A batch takes at most ``max(1, floor(source_cap_fraction * size))`` stems per source song
  (about 5 percent). If the cap or zero weights leave too few candidates, the batch is shorter.

Sampling is weighted without replacement (Efraimidis-Spirakis keys), seeded for reproducibility.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterable, Sequence

from .insights import Insight
from .state import FatigueModel


@dataclass(frozen=True)
class StemCandidate:
    stem_id: str
    source_id: str
    taste_score: float          # from the taste model, in [0, 1]
    start_ms: int = 0
    end_ms: int | None = None   # None: the whole stem


@dataclass(frozen=True)
class SelectionConfig:
    source_cap_fraction: float = 0.05
    novelty_max: float = 0.5


DEFAULT_SELECTION = SelectionConfig()


def novelty_bonus(exposures: int, cfg: SelectionConfig = DEFAULT_SELECTION) -> float:
    return 1.0 + cfg.novelty_max / (1.0 + max(0, exposures))


def selection_weight(taste_score: float, fatigue: float, novelty: float) -> float:
    return max(0.0, taste_score) * (1.0 - min(1.0, max(0.0, fatigue))) * max(0.0, novelty)


def source_cap(batch_size: int, fraction: float = DEFAULT_SELECTION.source_cap_fraction) -> int:
    return max(1, math.floor(batch_size * fraction + 1e-9))


def blocked_by_insight(c: StemCandidate, insights: Iterable[Insight]) -> bool:
    end = math.inf if c.end_ms is None else c.end_ms
    return any(i.confirmed and i.track_id == c.source_id and i.start_ms < end and c.start_ms < i.end_ms
               for i in insights)


def candidate_weight(c: StemCandidate, model: FatigueModel, at_s: float,
                     cfg: SelectionConfig = DEFAULT_SELECTION, insights: Sequence[Insight] = ()) -> float:
    stem, src = f"stem:{c.stem_id}", f"source:{c.source_id}"
    if model.is_disliked(stem) or model.is_disliked(src) or blocked_by_insight(c, insights):
        return 0.0
    fatigue = 1.0 - (1.0 - model.fatigue(stem, at_s)) * (1.0 - model.fatigue(src, at_s))
    return selection_weight(c.taste_score, fatigue, novelty_bonus(model.exposures(stem), cfg))


def select_batch(candidates: Sequence[StemCandidate], size: int, model: FatigueModel, at_s: float,
                 rng: random.Random, cfg: SelectionConfig = DEFAULT_SELECTION,
                 insights: Sequence[Insight] = ()) -> list[StemCandidate]:
    cap = source_cap(size, cfg.source_cap_fraction)
    keyed = []
    for c in candidates:
        w = candidate_weight(c, model, at_s, cfg, insights)
        if w > 0:
            keyed.append((rng.random() ** (1.0 / w), c))
    keyed.sort(key=lambda kc: kc[0], reverse=True)
    out: list[StemCandidate] = []
    per_source: dict[str, int] = {}
    for _, c in keyed:
        if len(out) >= size:
            break
        if per_source.get(c.source_id, 0) >= cap:
            continue
        per_source[c.source_id] = per_source.get(c.source_id, 0) + 1
        out.append(c)
    return out

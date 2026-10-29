"""Per-user thresholds tuned by the user's answers: pure, bounded and logged (decision 0021).

Update rule for a threshold ``t`` with bounds ``[floor, ceiling]``:

- "No, I like it" (a false positive):   ``t <- t + up * (ceiling - t)``
- "Yes, skip it from now on" (correct):  ``t <- t - down * (t - floor)``
- "Not sure yet":                        unchanged

Each step moves a fixed fraction of the remaining distance, so ``t`` stays inside the bounds for any
sequence of answers. It approaches the ceiling or floor geometrically but never passes it. ``up`` is
larger than ``down``, so a false positive costs more than a correct insight earns.

Keys:

- ``detector.min_skip_rate``: the T-014 detector's skip-rate threshold for this user.
- ``cause:<cause>``: confidence needed to surface an insight of that cause (similar windows).
- ``track:<track_id>``: confidence needed for further insights on the same track.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DETECTOR_KEY = "detector.min_skip_rate"


@dataclass(frozen=True)
class Bound:
    base: float
    floor: float
    ceiling: float
    up: float
    down: float

    def __post_init__(self):
        if not (0 <= self.floor <= self.base <= self.ceiling <= 1):
            raise ValueError("need 0 <= floor <= base <= ceiling <= 1")
        if not (0 <= self.up < 1 and 0 <= self.down < 1):
            raise ValueError("steps must be in [0, 1)")


@dataclass(frozen=True)
class TuningConfig:
    skip_rate: Bound = Bound(base=0.6, floor=0.5, ceiling=0.85, up=0.1, down=0.05)
    cause: Bound = Bound(base=0.6, floor=0.55, ceiling=0.9, up=0.25, down=0.1)
    track: Bound = Bound(base=0.6, floor=0.55, ceiling=0.95, up=0.5, down=0.1)

    def bound(self, key: str) -> Bound:
        if key == DETECTOR_KEY:
            return self.skip_rate
        if key.startswith("cause:"):
            return self.cause
        if key.startswith("track:"):
            return self.track
        raise KeyError(key)


DEFAULT_TUNING = TuningConfig()


def step(t: float, answer: str, b: Bound) -> float:
    """The update rule. Pure; the result is always within ``[b.floor, b.ceiling]``."""
    if answer not in ("yes", "no", "unsure"):
        raise ValueError(f"answer must be yes, no or unsure, not {answer!r}")
    t = min(max(t, b.floor), b.ceiling)
    if answer == "no":
        t += b.up * (b.ceiling - t)
    elif answer == "yes":
        t -= b.down * (t - b.floor)
    return round(min(max(t, b.floor), b.ceiling), 6)


@dataclass(frozen=True)
class ThresholdChange:
    key: str
    old: float
    new: float
    answer: str
    insight_id: str
    day: str


@dataclass
class Thresholds:
    values: dict[str, float] = field(default_factory=dict)

    def get(self, key: str, cfg: TuningConfig = DEFAULT_TUNING) -> float:
        return self.values.get(key, cfg.bound(key).base)

    def surface(self, cause: str, track_id: str, cfg: TuningConfig = DEFAULT_TUNING) -> float:
        return max(self.get(f"cause:{cause}", cfg), self.get(f"track:{track_id}", cfg))

    def min_skip_rate(self, cfg: TuningConfig = DEFAULT_TUNING) -> float:
        return self.get(DETECTOR_KEY, cfg)


def apply_answer(th: Thresholds, answer: str, *, cause: str, track_id: str, insight_id: str, day: str,
                 cfg: TuningConfig = DEFAULT_TUNING) -> tuple[Thresholds, list[ThresholdChange]]:
    """New thresholds after one answer, plus a log entry per key that moved."""
    values = dict(th.values)
    changes = []
    for key in (DETECTOR_KEY, f"cause:{cause}", f"track:{track_id}"):
        old = th.get(key, cfg)
        new = step(old, answer, cfg.bound(key))
        if new != old:
            values[key] = new
            changes.append(ThresholdChange(key, old, new, answer, insight_id, day))
    return Thresholds(values), changes

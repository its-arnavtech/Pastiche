"""Insight lifecycle: proposed -> shown -> confirmed | dismissed | not_sure (decision 0021).

- Delivery is to the passive inbox only. There is no other channel: nothing pops up and nothing
  touches playback. The user opens the inbox when they want to.
- At most ``max_new_per_day`` new insights move from proposed to shown per local day (highest
  confidence first). A not-sure insight that returns after its delay has its own small cap.
- "Not sure yet" moves an insight to ``not_sure`` for ``not_sure_delay_days``, then it is shown again.
- "No, I like it" dismisses it. Overlapping windows of that track version are never proposed again,
  and the tuning step raises the threshold for similar windows.
- Only ``confirmed`` insights reach selection (``selection_insights``). Every other state maps to
  ``confirmed=False``, which selection ignores.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass
from typing import Iterable, Mapping

from remixer.fatigue.insights import Insight

STATES = ("proposed", "shown", "confirmed", "dismissed", "not_sure")
ANSWER_STATE = {"yes": "confirmed", "no": "dismissed", "unsure": "not_sure"}
CHANNEL = "inbox"


@dataclass(frozen=True)
class LifecycleConfig:
    max_new_per_day: int = 1
    max_resurface_per_day: int = 1
    not_sure_delay_days: int = 7


DEFAULT_LIFECYCLE = LifecycleConfig()


@dataclass(frozen=True)
class InsightRecord:
    insight_id: str
    track_id: str
    track_version: str
    start_ms: int
    end_ms: int
    sentence: str
    hypothesis: str
    cause: str
    confidence: float
    skipped: int
    reached: int
    proposed_day: str
    state: str = "proposed"
    channel: str = CHANNEL
    shown_day: str | None = None
    answer: str | None = None
    answered_day: str | None = None
    ask_again_on: str | None = None
    times_shown: int = 0

    def __post_init__(self):
        if self.state not in STATES:
            raise ValueError(f"state {self.state!r} not in {STATES}")
        if self.channel != CHANNEL:
            raise ValueError("insights are delivered to the passive inbox only")

    @property
    def pending(self) -> bool:
        """Waiting for an answer in the inbox (what the badge counts)."""
        return self.state == "shown"

    def overlaps(self, track_id: str, track_version: str, start_ms: int, end_ms: int) -> bool:
        return ((self.track_id, self.track_version) == (track_id, track_version)
                and start_ms < self.end_ms and self.start_ms < end_ms)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: Mapping) -> "InsightRecord":
        return cls(**d)


def add_days(day: str, n: int) -> str:
    return (dt.date.fromisoformat(day) + dt.timedelta(days=n)).isoformat()


def answer(rec: InsightRecord, value: str, day: str, cfg: LifecycleConfig = DEFAULT_LIFECYCLE) -> InsightRecord:
    """The user's answer. Allowed from any state, so the user can change their mind."""
    if value not in ANSWER_STATE:
        raise ValueError(f"answer must be yes, no or unsure, not {value!r}")
    return dataclasses.replace(
        rec, state=ANSWER_STATE[value], answer=value, answered_day=day,
        ask_again_on=add_days(day, cfg.not_sure_delay_days) if value == "unsure" else None)


def deliver(records: Mapping[str, InsightRecord], day: str,
            cfg: LifecycleConfig = DEFAULT_LIFECYCLE) -> tuple[dict[str, InsightRecord], list[str]]:
    """Move insights into the inbox for ``day``; returns the new records and the ids shown today."""
    out = dict(records)
    shown_new = sum(1 for r in out.values() if r.shown_day == day and r.times_shown == 1)
    shown_again = sum(1 for r in out.values() if r.shown_day == day and r.times_shown > 1)
    delivered = []
    due = sorted((r for r in out.values() if r.state == "not_sure" and r.ask_again_on and r.ask_again_on <= day),
                 key=lambda r: (r.ask_again_on, r.insight_id))
    for r in due[:max(0, cfg.max_resurface_per_day - shown_again)]:
        out[r.insight_id] = dataclasses.replace(r, state="shown", answer=None, ask_again_on=None,
                                                shown_day=day, times_shown=r.times_shown + 1)
        delivered.append(r.insight_id)
    queue = sorted((r for r in out.values() if r.state == "proposed"),
                   key=lambda r: (-r.confidence, r.proposed_day, r.insight_id))
    for r in queue[:max(0, cfg.max_new_per_day - shown_new)]:
        out[r.insight_id] = dataclasses.replace(r, state="shown", shown_day=day, times_shown=1)
        delivered.append(r.insight_id)
    return out, delivered


def suppressed_by(records: Iterable[InsightRecord], track_id: str, track_version: str,
                  start_ms: int, end_ms: int) -> InsightRecord | None:
    """A dismissed insight overlapping this window, if any."""
    return next((r for r in records if r.state == "dismissed"
                 and r.overlaps(track_id, track_version, start_ms, end_ms)), None)


def to_selection_insight(rec: InsightRecord) -> Insight:
    return Insight(insight_id=rec.insight_id, track_id=rec.track_id, track_version=rec.track_version,
                   start_ms=rec.start_ms, end_ms=rec.end_ms, hypothesis=rec.sentence,
                   confirmed=rec.state == "confirmed", answer=rec.answer)


def selection_insights(records: Iterable[InsightRecord]) -> list[Insight]:
    """Every insight in selection's form; only ``confirmed`` ones have ``confirmed=True``."""
    return [to_selection_insight(r) for r in sorted(records, key=lambda r: r.insight_id)]

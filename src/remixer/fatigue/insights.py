"""Insights: advisory hypotheses about disliked windows, inert until the user confirms them.

An insight starts with ``confirmed = False``. Only the user's "Yes, skip it from now on" sets it;
"No, I like it" dismisses it; "Not sure yet" leaves it pending. Selection ignores every insight
that is not confirmed. Insights sit in a passive inbox and never interrupt playback.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Iterable

ANSWERS = {"insight_yes": "yes", "insight_no": "no", "insight_unsure": "unsure"}


@dataclass(frozen=True)
class Insight:
    insight_id: str
    track_id: str
    track_version: str
    start_ms: int
    end_ms: int
    hypothesis: str
    confirmed: bool = False
    answer: str | None = None   # yes | no | unsure

    @property
    def pending(self) -> bool:
        return self.answer in (None, "unsure")


def insights_from_candidates(candidates: Iterable) -> list[Insight]:
    """Merge adjacent candidate windows (``WindowStats`` from T-014) into one insight each."""
    rows = sorted(candidates, key=lambda c: (c.track_id, c.track_version, c.window_index))
    out: list[Insight] = []
    run: list = []

    def flush():
        if not run:
            return
        a, b = run[0], run[-1]
        rate = sum(c.skipped for c in run) / max(1, sum(c.reached for c in run))
        out.append(Insight(
            insight_id=f"{a.track_id}:{a.track_version}:{a.start_ms}-{b.end_ms}",
            track_id=a.track_id, track_version=a.track_version, start_ms=a.start_ms, end_ms=b.end_ms,
            hypothesis=(f"You usually skip {a.start_ms // 1000}s-{b.end_ms // 1000}s of this track "
                        f"({rate:.0%} of the listens that reached it).")))
        run.clear()

    for c in rows:
        if run and (c.track_id, c.track_version) == (run[-1].track_id, run[-1].track_version) \
                and c.window_index == run[-1].window_index + 1:
            run.append(c)
        else:
            flush()
            run.append(c)
    flush()
    return out


def answer(insight: Insight, value: str) -> Insight:
    if value not in ("yes", "no", "unsure"):
        raise ValueError(f"answer must be yes, no or unsure, not {value!r}")
    return dataclasses.replace(insight, answer=value, confirmed=value == "yes")


def apply_answer_events(insights: Iterable[Insight], events: Iterable) -> list[Insight]:
    """Apply ``insight_yes|no|unsure`` events (``payload.insight_id``) in wall-time order."""
    by_id = {i.insight_id: i for i in insights}
    for e in sorted((e for e in events if e.event_type in ANSWERS), key=lambda e: e.wall_time):
        iid = (e.payload or {}).get("insight_id")
        if iid in by_id:
            by_id[iid] = answer(by_id[iid], ANSWERS[e.event_type])
    return list(by_id.values())


def confirmed(insights: Iterable[Insight]) -> list[Insight]:
    return [i for i in insights if i.confirmed]

"""Delivery is a passive inbox: one new insight a day, dismissal suppresses, only confirmed counts."""
import pytest

from remixer.fatigue.selection import StemCandidate, candidate_weight
from remixer.fatigue.state import FatigueModel
from remixer.insights.lifecycle import (
    DEFAULT_LIFECYCLE, InsightRecord, answer, deliver, selection_insights, suppressed_by,
)


def rec(i: int, confidence: float, state: str = "proposed") -> InsightRecord:
    return InsightRecord(f"id{i}", "song", "v1", i * 5000, (i + 1) * 5000, f"sentence {i}", "why",
                         "unknown", confidence, 4, 5, "2026-10-01", state)


def test_at_most_one_new_insight_per_day_highest_confidence_first():
    records = {r.insight_id: r for r in (rec(1, 0.7), rec(2, 0.9), rec(3, 0.8))}
    out, shown = deliver(records, "2026-10-02")
    assert shown == ["id2"]
    assert out["id2"].state == "shown" and out["id2"].channel == "inbox"
    again, shown2 = deliver(out, "2026-10-02")
    assert shown2 == [] and again == out
    nxt, shown3 = deliver(out, "2026-10-03")
    assert shown3 == ["id3"]


def test_not_sure_comes_back_only_after_the_delay():
    shown = rec(1, 0.9, "shown")
    shown = InsightRecord(**{**shown.to_dict(), "times_shown": 1, "shown_day": "2026-10-01"})
    held = answer(shown, "unsure", "2026-10-01")
    assert held.state == "not_sure" and held.ask_again_on == "2026-10-08"
    out, ids = deliver({held.insight_id: held}, "2026-10-07")
    assert ids == [] and out[held.insight_id].state == "not_sure"
    out, ids = deliver(out, "2026-10-08")
    assert ids == [held.insight_id] and out[held.insight_id].state == "shown"
    assert out[held.insight_id].times_shown == 2 and out[held.insight_id].answer is None


def test_dismissal_suppresses_and_only_confirmed_blocks_selection():
    shown = rec(1, 0.9, "shown")
    dismissed = answer(shown, "no", "2026-10-01")
    assert dismissed.state == "dismissed" and dismissed.ask_again_on is None
    assert suppressed_by([dismissed], "song", "v1", 5000, 9000) is dismissed
    assert suppressed_by([dismissed], "song", "v1", 10_000, 15_000) is None
    model = FatigueModel()
    stem = StemCandidate("stem", "song", 0.8, 5000, 10_000)
    base = candidate_weight(stem, model, 0.0)
    pending = selection_insights([shown, answer(rec(2, 0.5, "shown"), "unsure", "2026-10-01")])
    assert all(i.confirmed is False for i in pending)
    assert candidate_weight(stem, model, 0.0, insights=pending) == base
    blocked = selection_insights([answer(shown, "yes", "2026-10-01")])
    assert blocked[0].confirmed and candidate_weight(stem, model, 0.0, insights=blocked) == 0.0


def test_there_is_no_delivery_channel_but_the_inbox():
    with pytest.raises(ValueError):
        InsightRecord("i", "t", "v", 0, 5000, "s", "h", "unknown", 0.5, 1, 1, "2026-10-01", channel="popup")
    assert DEFAULT_LIFECYCLE.max_new_per_day == 1

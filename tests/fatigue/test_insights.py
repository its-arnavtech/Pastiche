import pytest

from remixer.analytics.events import Event
from remixer.analytics.heatmap import build_heatmap
from remixer.analytics.simulate import Player, TrackSpec
from remixer.fatigue.insights import (
    Insight, answer, apply_answer_events, confirmed, insights_from_candidates,
)


def candidates():
    t = TrackSpec("t1", "v1", 120_000)
    p = Player("s")
    for _ in range(3):
        p.load(t).play().listen_to(30_500).fwd().wait(300).fwd().listen_to(120_000).end()
        p.wait(1000)
    return build_heatmap(p.events).candidates()


def test_adjacent_candidate_windows_become_one_unconfirmed_insight():
    (ins,) = insights_from_candidates(candidates())
    assert (ins.track_id, ins.start_ms, ins.end_ms) == ("t1", 30_000, 40_000)
    assert ins.confirmed is False and ins.answer is None and ins.pending
    assert "30s-40s" in ins.hypothesis


def test_answers():
    ins = Insight("i", "t", "v1", 0, 5000, "h")
    assert answer(ins, "yes").confirmed
    assert not answer(ins, "no").confirmed and not answer(ins, "no").pending
    assert not answer(ins, "unsure").confirmed and answer(ins, "unsure").pending
    with pytest.raises(ValueError):
        answer(ins, "maybe")


def test_answer_events_apply_in_order_and_only_yes_confirms():
    a, b = Insight("a", "t", "v1", 0, 5000, "h"), Insight("b", "t", "v1", 5000, 10_000, "h")
    evs = [Event("2", "s", "t", "v1", "insight_no", 0, 2000, "source", {}, {"insight_id": "a"}),
           Event("1", "s", "t", "v1", "insight_yes", 0, 1000, "source", {}, {"insight_id": "a"}),
           Event("3", "s", "t", "v1", "insight_yes", 0, 3000, "source", {}, {"insight_id": "b"}),
           Event("4", "s", "t", "v1", "insight_yes", 0, 3000, "source", {}, {"insight_id": "zzz"})]
    out = {i.insight_id: i for i in apply_answer_events([a, b], evs)}
    assert out["a"].answer == "no" and not out["a"].confirmed
    assert [i.insight_id for i in confirmed(out.values())] == ["b"]

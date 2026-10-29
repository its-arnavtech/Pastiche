"""T-014 detector -> insight inbox -> user answer -> selection, end to end on simulated events."""
import random

from remixer.analytics.events import Event
from remixer.analytics.heatmap import build_heatmap
from remixer.analytics.interpret import interpret
from remixer.analytics.simulate import simulate
from remixer.fatigue.insights import apply_answer_events, insights_from_candidates
from remixer.fatigue.selection import StemCandidate, candidate_weight, select_batch
from remixer.fatigue.state import replay


def test_insight_affects_selection_only_after_the_user_confirms():
    sim = simulate(n_tracks=20, n_sessions=300, seed=8)
    insights = insights_from_candidates(build_heatmap(sim.events).candidates())
    assert insights and not any(i.confirmed for i in insights)

    target = insights[0]
    mid = (target.start_ms + target.end_ms) // 2
    inside = StemCandidate("vox-1", target.track_id, 0.9, mid - 500, mid + 500)
    model = replay([], signals=interpret(sim.events).signals)
    at_s = sim.events[-1].wall_time / 1000

    assert candidate_weight(inside, model, at_s, insights=insights) > 0

    yes = Event("ans", "inbox", target.track_id, target.track_version, "insight_yes", target.start_ms,
                sim.events[-1].wall_time + 1, "source", {}, {"insight_id": target.insight_id})
    answered = apply_answer_events(insights, [yes])
    assert candidate_weight(inside, model, at_s, insights=answered) == 0
    batch = select_batch([inside, StemCandidate("drm-2", "other", 0.5)], 2, model, at_s,
                         random.Random(0), insights=answered)
    assert [c.stem_id for c in batch] == ["drm-2"]


def test_passive_signals_shape_fatigue_but_never_rate():
    sim = simulate(n_tracks=20, n_sessions=200, seed=9)
    model = replay([], signals=interpret(sim.events).signals)
    assert model.states, "early nexts should add some fatigue"
    assert not any(s.disliked or s.liked or s.taste_evidence for s in model.states.values())

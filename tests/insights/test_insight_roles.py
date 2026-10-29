"""The three roles fall back on bad model output and the Skeptic's rules reject confounds."""
from remixer.insights.cost import CallBudget, Caller, ResponseCache
from remixer.insights.evidence import History, runs_from_candidates
from remixer.insights.llm import MockLLM, by_role
from remixer.insights.mock import heuristic_script
from remixer.insights.roles import analyst, narrator, rule_reasons, rule_verdict, skeptic

from insight_helpers import history_skipping, session, skip_at


def evidence_for(events, track_id):
    hist = History(events)
    (run,) = [r for r in runs_from_candidates(hist.heatmap.candidates()) if r.track_id == track_id]
    return hist.evidence(run)


def caller(script, budget=10):
    return Caller(MockLLM(script), ResponseCache(), CallBudget(budget), "2026-10-01")


def test_rules_reject_an_intro_a_one_off_and_undone_skips():
    intro = evidence_for(history_skipping("intro", 6, at_ms=400), "intro")
    assert rule_verdict(rule_reasons(intro)) == "reject"
    assert any(r.code == "intro" for r in rule_reasons(intro))

    kept = [e for i in range(5) for e in session("undo", i, lambda p, t: skip_at(p, t, 20_000))]
    backed = [e for i in range(5, 6) for e in session("undo", i, lambda p, t: skip_at(p, t, 20_000, undo=True))]
    undone = evidence_for(kept + backed, "undo")
    reasons = rule_reasons(undone)
    assert any(r.code == "undo" for r in reasons) and rule_verdict(reasons) == "reject"


def test_malformed_output_falls_back_per_role_and_never_raises():
    ev = evidence_for(history_skipping("song", 6), "song")
    c = caller(lambda request, system: "this is not json")
    hyp = analyst(c, [ev])
    assert hyp.by_window[ev.window_id].source == "fallback"
    verdict = skeptic(c, [ev], hyp.by_window)
    assert verdict.by_window[ev.window_id].verdict == "accept"
    told = narrator(c, [ev])
    assert told.by_window[ev.window_id].source == "fallback"
    assert told.by_window[ev.window_id].sentence == "You've skipped 0:20-0:25 in 6 of 6 listens."
    assert c.stats.invalid >= 3 and c.stats.errors == 0


def test_a_sentence_with_invented_counts_is_replaced():
    ev = evidence_for(history_skipping("song", 6), "song")
    hyp = analyst(caller(heuristic_script), [ev])

    def lie(request, system):
        if request["role"] == "narrator":
            return {"items": [{"window_id": it["window_id"], "sentence": "You've skipped 0:20-0:25 in 9 of 9 listens."}
                              for it in request["items"]]}
        return by_role(analyst=lambda r, s: {"items": []})(request, system)

    c = caller(lie)
    told = narrator(c, [ev])
    assert told.by_window[ev.window_id].source == "fallback"
    assert "6 of 6" in told.by_window[ev.window_id].sentence
    assert told.errors
    assert hyp.by_window[ev.window_id].confidence > 0


def test_a_downgrade_without_a_reason_is_rejected():
    ev = evidence_for(history_skipping("song", 6), "song")
    hyp = analyst(caller(heuristic_script), [ev])

    def bare(request, system):
        return {"items": [{"window_id": it["window_id"], "verdict": "reject", "confidence": 0.1,
                           "reasons": [{"code": "none", "detail": "nope"}]} for it in request["items"]]}

    c = caller(by_role(skeptic=bare))
    verdict = skeptic(c, [ev], hyp.by_window)
    assert verdict.errors
    assert verdict.by_window[ev.window_id].source == "rules"

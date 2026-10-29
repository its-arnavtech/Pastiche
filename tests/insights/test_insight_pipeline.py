"""The nightly pipeline: real dislikes surface, confounds do not, and the budget holds."""
from remixer.insights.evaluate import evaluate
from remixer.insights.llm import MockLLM
from remixer.insights.mock import garbage_script, heuristic_script
from remixer.insights.pipeline import InsightConfig, InsightState, run_nightly
from remixer.insights.scenarios import CONFOUNDS, confound_world, score

from insight_helpers import DAY, answer_event, history_skipping, session


def night(events, state=None, llm=None, now=None, cfg=None):
    now = now if now is not None else max(e.wall_time for e in events) + 1000
    return run_nightly(events, state or InsightState(), llm or MockLLM(heuristic_script), now, cfg=cfg or InsightConfig())


def test_a_repeated_skip_becomes_one_inbox_sentence_and_a_second_night_is_free():
    events = history_skipping("song", 6)
    state, report = night(events)
    (rec,) = state.records.values()
    assert rec.state == "shown" and rec.sentence == "You've skipped 0:20-0:25 in 6 of 6 listens."
    assert report.delivered == [rec.insight_id] and report.llm["calls"] == 3
    again, report2 = night(events, state, now=max(e.wall_time for e in events) + 1000)
    assert report2.llm["calls"] == 0 and report2.known == 1
    assert again.to_json() == InsightState.from_json(again.to_json()).to_json()


def test_three_listens_are_required_and_confounds_never_reach_the_model():
    short = history_skipping("song", 2)
    state, report = night(short)
    assert state.records == {} and report.llm["calls"] == 0

    early = [e for i in range(2) for e in session("song", i, lambda p, t: p.load(t).play().listen_to(5000).next())]
    state, report = night(history_skipping("song", 2, at_ms=40_000) + early)
    assert state.records == {} and report.waiting == 1 and report.llm["calls"] == 0

    intro, report = night(history_skipping("intro", 6, at_ms=300))
    assert intro.records == {} and report.rule_rejected == 1 and report.llm["calls"] == 0
    assert report.decisions[0]["reasons"] == ["intro"]


def test_one_new_insight_a_day_dismissal_suppresses_and_not_sure_waits():
    events = history_skipping("a", 6) + history_skipping("b", 6)
    state, report = night(events)
    assert len(report.delivered) == 1 and len(state.records) == 2
    shown = state.records[report.delivered[0]]
    other = next(r for r in state.records.values() if r.state == "proposed")

    later = max(e.wall_time for e in events) + DAY
    answered = events + [answer_event(shown.insight_id, "insight_no", later - 1000, shown.track_id)]
    state, report = night(answered, state, now=later)
    assert state.records[shown.insight_id].state == "dismissed"
    assert report.suppressed == 1
    assert state.thresholds.surface(shown.cause, shown.track_id) > 0.6
    assert any(c.key == "track:" + shown.track_id for c in report.threshold_changes)

    held = events + [answer_event(other.insight_id, "insight_unsure", later - 500, other.track_id)]
    fresh, _ = night(events)
    fresh, report = night(held, fresh, now=later)
    assert fresh.records[other.insight_id].state == "not_sure"
    back, report = night(held, fresh, now=later + 7 * DAY)
    assert back.records[other.insight_id].state == "shown"
    assert back.records[other.insight_id].times_shown == 1


def test_garbage_and_a_dead_backend_fall_back_without_crashing():
    events = history_skipping("song", 6)
    state, report = night(events, llm=MockLLM(garbage_script))
    (rec,) = state.records.values()
    assert rec.sentence.startswith("You've skipped 0:20-0:25")
    assert report.llm["invalid"] >= 1 and report.errors

    def down(request, system):
        raise ConnectionError("backend down")

    state, report = night(events, llm=MockLLM(down))
    assert state.records and report.llm["errors"] >= 1 and report.llm["calls"] >= 1


def test_the_daily_budget_defers_work_and_a_warm_cache_spends_nothing():
    events = history_skipping("a", 6) + history_skipping("b", 6) + history_skipping("c", 6)
    cfg = InsightConfig(daily_call_budget=2)
    state, report = night(events, cfg=cfg)
    assert report.llm["calls"] == 2 and report.deferred >= 1 and report.llm["denied"] >= 1
    state, report2 = night(events, state, cfg=cfg)
    assert report2.llm["calls"] <= 2

    full, _ = night(events)
    cached = InsightState(cache=full.cache)
    _, replay = night(events, cached)
    assert replay.llm["calls"] == 0 and replay.llm["cache_hits"] >= 3


def test_planted_dislikes_surface_and_planted_confounds_do_not():
    report = evaluate(seeds=3)
    for name in ("heuristic", "always_accept", "garbage"):
        v = report["variants"][name]
        assert v["precision"] >= 0.9, name
        assert v["recall"] >= 0.95, name
        assert set(v["surfaced_by_kind"]) <= {"dislike", "undo", "time_of_day"}
        assert v["surfaced_by_kind"].get("undo", 0) <= 6
        assert v["surfaced_by_kind"].get("time_of_day", 0) <= 4
        for kind in CONFOUNDS:
            if kind not in ("undo", "time_of_day"):
                assert v["surfaced_by_kind"].get(kind, 0) == 0
    assert report["variants"]["garbage"]["invalid_replies"] == report["variants"]["garbage"]["llm_calls"]
    budget = report["cache_and_budget_seed0"]
    assert budget["same_night_rerun_calls"] == 0
    assert budget["replay_with_warm_cache_calls"] == 0
    assert budget["insights_shown_per_day_max"] == 1
    assert budget["tight_budget_max_calls_in_a_night"] <= budget["tight_budget"]
    assert budget["tight_budget_deferred_windows"] > 0

    world = confound_world(seed=0)
    state = InsightState()
    cfg = InsightConfig(utc_offset_minutes=world.utc_offset_minutes)
    for now in world.night_ends():
        state, _ = run_nightly(world.events, state, MockLLM(heuristic_script), now, world.features, cfg)
    got = score(state.records.values(), world)
    assert got["precision"] >= 0.9 and got["recall"] >= 0.9
    assert all(r.channel == "inbox" and r.state in ("shown", "proposed") for r in state.records.values())
    assert all(e.client_info.get("synthetic") is True for e in world.events)

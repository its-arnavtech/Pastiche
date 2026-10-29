import pytest

from remixer.analytics.events import Event
from remixer.analytics.interpret import Signal
from remixer.fatigue.credit import StemUse
from remixer.fatigue.state import FatigueConfig, FatigueModel, replay

DAY = 86_400.0
CFG = FatigueConfig(half_life_s=2 * DAY)


def test_tired_decays_exponentially_with_half_life():
    m = FatigueModel(CFG)
    m.tired({"source:a": 1.0}, at_s=0)
    f0 = m.fatigue("source:a", 0)
    assert f0 == pytest.approx(0.6)
    assert m.fatigue("source:a", 2 * DAY) == pytest.approx(0.3)
    assert m.fatigue("source:a", 4 * DAY) == pytest.approx(0.15)
    assert m.fatigue("source:a", 60 * DAY) < 1e-4  # a rested song can return


def test_increments_saturate_below_one():
    m = FatigueModel(CFG)
    for _ in range(20):
        m.tired({"stem:x": 1.0}, at_s=0)
    assert 0.99 < m.fatigue("stem:x", 0) < 1.0


def test_thumbs_down_is_permanent_and_clear_resets_it():
    m = FatigueModel(CFG)
    m.down({"source:a": 1.0}, at_s=0, direct=True)
    assert m.is_disliked("source:a")
    assert m.fatigue("source:a", 365 * DAY) < 1e-6
    assert m.is_disliked("source:a")
    m.clear("source:a")
    assert not m.is_disliked("source:a")


def test_tired_is_not_a_dislike():
    m = FatigueModel(CFG)
    m.tired({"source:a": 1.0}, at_s=0)
    assert not m.is_disliked("source:a")
    assert m.taste_evidence("source:a") == 0.0


def test_thumbs_up_relieves_fatigue_and_adds_taste():
    m = FatigueModel(CFG)
    m.tired({"source:a": 1.0}, at_s=0)
    m.up({"source:a": 1.0}, at_s=0, direct=True)
    assert m.fatigue("source:a", 0) == pytest.approx(0.3)
    assert m.taste_evidence("source:a") == 1.0
    assert m.states["source:a"].liked


def table_neighbors(stem, k):
    return [("near", 0.9), ("far", 0.2), (stem, 1.0)][:k]


def test_negative_on_a_stem_propagates_smaller_penalty_to_neighbors():
    m = FatigueModel(FatigueConfig(neighbor_factor=0.5), neighbors=table_neighbors)
    m.tired({"stem:a": 1.0}, at_s=0)
    fa, fn, ff = (m.fatigue(f"stem:{s}", 0) for s in ("a", "near", "far"))
    assert fa == pytest.approx(0.6)
    assert fn == pytest.approx(0.6 * 0.5 * 0.9)
    assert ff == pytest.approx(0.6 * 0.5 * 0.2)
    assert fa > fn > ff > 0
    assert not m.is_disliked("stem:near")


def test_propagation_is_one_hop_and_only_for_stems():
    calls = []

    def lookup(stem, k):
        calls.append(stem)
        return [("b", 1.0)]

    m = FatigueModel(neighbors=lookup)
    m.tired({"stem:a": 1.0}, at_s=0)
    m.tired({"source:song": 1.0}, at_s=0)
    assert calls == ["a"]


def test_passive_signals_never_create_ratings():
    m = FatigueModel(CFG)
    m.passive_next({"source:a": 1.0}, "early_next", at_s=0)
    m.exposure({"source:a": 1.0}, at_s=0)
    st = m.states["source:a"]
    assert (st.disliked, st.liked, st.taste_evidence) == (False, False, 0.0)
    assert st.exposures == 1
    assert 0 < m.fatigue("source:a", 0) < 0.2


def ev(i, typ, track, kind, wall_s, payload=None):
    return Event(f"e{i}", "s", track, "v1", typ, 0, int(wall_s * 1000), kind, {}, payload or {})


RECIPE = [StemUse("drm", "songA", 0, 60_000, -10.0), StemUse("vox", "songB", 0, 60_000, -10.0)]


def recipes(track_id, version):
    return RECIPE if track_id == "gen1" else None


def test_replay_credits_generated_track_ratings_to_stems():
    m = replay([ev(1, "rate_down", "gen1", "generated", 0)], recipes)
    assert m.is_disliked("track:gen1")
    assert not m.is_disliked("stem:drm") and not m.is_disliked("stem:vox")
    assert m.taste_evidence("stem:drm") == pytest.approx(-0.5)
    assert m.taste_evidence("stem:vox") == pytest.approx(-0.5)


def test_replay_direct_stem_rating_and_source_rating():
    m = replay([ev(1, "rate_down", "gen1", "generated", 0, {"stem_id": "vox"}),
                ev(2, "rate_tired", "songA", "source", 10)], recipes)
    assert m.is_disliked("stem:vox") and not m.is_disliked("stem:drm")
    assert m.fatigue("source:songA", 10) == pytest.approx(0.6)


def test_replay_is_order_independent_of_input_and_clear_works():
    events = [ev(2, "rate_clear", "songA", "source", 20), ev(1, "rate_down", "songA", "source", 0)]
    assert not replay(events).is_disliked("source:songA")
    assert replay(events[1:]).is_disliked("source:songA")


def test_replay_folds_in_track_level_passive_signals():
    sig = Signal("s", "songA", "v1", "source", "early_next", "track", -1.0, 5000)
    m = replay([], signals=[sig])
    assert m.fatigue("source:songA", 5) == pytest.approx(0.1)
    assert not m.is_disliked("source:songA")

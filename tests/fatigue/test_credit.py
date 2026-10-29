import pytest

from remixer.fatigue.credit import CreditConfig, StemUse, assign_credit, loudness_shares


def recipe():
    return [
        StemUse("drums", "songA", 0, 60_000, -14.0),
        StemUse("bass", "songB", 0, 60_000, -14.0),
        StemUse("vox", "songC", 30_000, 60_000, -4.0),   # 10 LU louder, half the time
        StemUse("pad", "songD", 0, 60_000, -70.0),       # below the audibility floor
    ]


def test_shares_sum_to_one_and_follow_loudness_and_time():
    s = loudness_shares(recipe())
    assert sum(s.values()) == pytest.approx(1.0)
    assert "pad" not in s
    assert s["drums"] == pytest.approx(s["bass"])
    # vox: 10x power for half the duration = 5x drums
    assert s["vox"] == pytest.approx(5 * s["drums"])


def test_window_level_credit_only_reaches_stems_audible_in_the_window():
    s = loudness_shares(recipe(), window=(10_000, 15_000))
    assert set(s) == {"drums", "bass"}
    assert s["drums"] == pytest.approx(0.5)


def test_assign_credit_scales_the_rating():
    c = assign_credit(-1.0, recipe(), window=(40_000, 45_000))
    assert sum(c.values()) == pytest.approx(-1.0)
    assert min(c, key=c.get) == "vox"


def test_floor_is_configurable_and_silence_gives_nothing():
    assert "pad" in loudness_shares(recipe(), cfg=CreditConfig(audible_floor_lufs=-80))
    assert loudness_shares([StemUse("x", "s", 0, 1000, -90.0)]) == {}
    assert loudness_shares(recipe(), window=(70_000, 80_000)) == {}


def test_same_stem_placed_twice_accumulates():
    r = [StemUse("a", "s", 0, 1000, -10.0), StemUse("a", "s", 2000, 3000, -10.0), StemUse("b", "t", 0, 2000, -10.0)]
    assert loudness_shares(r) == pytest.approx({"a": 0.5, "b": 0.5})

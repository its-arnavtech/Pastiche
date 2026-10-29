"""Threshold updates are bounded: a long run of answers cannot reach 0 or 1."""
import random

import pytest

from remixer.insights.tuning import (
    DEFAULT_TUNING, DETECTOR_KEY, Bound, Thresholds, TuningConfig, apply_answer, step,
)


def test_step_moves_toward_the_bound_and_stays_inside_it():
    b = DEFAULT_TUNING.skip_rate
    up = step(b.base, "no", b)
    down = step(b.base, "yes", b)
    assert b.base < up <= b.ceiling
    assert b.floor <= down < b.base
    assert step(b.base, "unsure", b) == b.base


def test_a_hundred_answers_never_pass_the_floor_or_ceiling():
    rng = random.Random(0)
    for bound in (DEFAULT_TUNING.skip_rate, DEFAULT_TUNING.cause, DEFAULT_TUNING.track):
        t = bound.base
        for _ in range(100):
            t = step(t, rng.choice(("yes", "no", "unsure")), bound)
            assert bound.floor <= t <= bound.ceiling
        assert step(bound.ceiling, "no", bound) == bound.ceiling
        assert step(bound.floor, "yes", bound) == bound.floor


def test_false_positives_cost_more_than_confirmations_earn():
    b = Bound(base=0.6, floor=0.5, ceiling=0.85, up=0.1, down=0.05)
    assert step(0.6, "no", b) - 0.6 > 0.6 - step(0.6, "yes", b)


def test_apply_answer_logs_every_key_and_raises_similar_windows():
    th, changes = apply_answer(Thresholds(), "no", cause="loudness_jump", track_id="song",
                               insight_id="song:v1:0-5000", day="2026-10-01")
    keys = {c.key for c in changes}
    assert keys == {DETECTOR_KEY, "cause:loudness_jump", "track:song"}
    assert all(c.new > c.old and c.answer == "no" for c in changes)
    assert th.surface("loudness_jump", "song") > DEFAULT_TUNING.cause.base
    assert th.surface("tempo_change", "other") == DEFAULT_TUNING.cause.base


def test_unknown_answer_is_rejected():
    with pytest.raises(ValueError):
        step(0.6, "maybe", DEFAULT_TUNING.skip_rate)
    with pytest.raises(ValueError):
        TuningConfig(skip_rate=Bound(0.6, 0.7, 0.5, 0.1, 0.05))

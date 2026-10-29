import random

import pytest

pytest.importorskip("numpy")

from remixer.fatigue.attribution import Observation, fit_attribution  # noqa: E402
from remixer.fatigue.credit import StemUse, loudness_shares  # noqa: E402


def simulate_ratings(seed, n_stems=40, n_ratings=300, culprits=("s07",), p_down_culprit=0.9,
                     p_down_base=0.25, per_recipe=5, shares=False):
    rng = random.Random(seed)
    stems = [f"s{i:02d}" for i in range(n_stems)]
    obs = []
    for _ in range(n_ratings):
        chosen = rng.sample(stems, per_recipe)
        if shares:
            recipe = [StemUse(s, s, 0, 60_000, rng.uniform(-20, -8)) for s in chosen]
            feats = loudness_shares(recipe)
        else:
            feats = {s: 1.0 for s in chosen}
        bad = any(c in chosen for c in culprits)
        down = rng.random() < (p_down_culprit if bad else p_down_base)
        obs.append(Observation(feats, -1.0 if down else 1.0))
    return obs


@pytest.mark.parametrize("seed", range(10))
def test_single_known_culprit_is_isolated(seed):
    att = fit_attribution(simulate_ratings(seed), lam=1.0)
    assert att.culprits(min_z=3.0) == ["s07"]
    assert min(att.coef, key=att.coef.get) == "s07"


@pytest.mark.parametrize("seed", range(5))
def test_two_culprits_are_both_found(seed):
    att = fit_attribution(simulate_ratings(seed, n_ratings=500, culprits=("s03", "s21")), lam=1.0)
    assert set(att.culprits(min_z=3.0)) == {"s03", "s21"}


def test_works_with_credit_shares_as_features():
    att = fit_attribution(simulate_ratings(1, n_ratings=600, shares=True), lam=0.3)
    assert att.culprits(min_z=3.0)[:1] == ["s07"]


def test_too_little_data_flags_nothing():
    att = fit_attribution(simulate_ratings(2, n_ratings=8), lam=1.0)
    assert att.culprits(min_z=3.0) == []


def test_no_culprit_no_flags():
    att = fit_attribution(simulate_ratings(4, culprits=(), n_ratings=400), lam=1.0)
    assert att.culprits(min_z=3.0) == []


def test_empty_input():
    att = fit_attribution([])
    assert att.coef == {} and att.culprits() == []

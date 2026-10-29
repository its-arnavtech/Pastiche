import random
from collections import Counter

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from remixer.fatigue.insights import Insight, answer
from remixer.fatigue.selection import (
    SelectionConfig, StemCandidate, candidate_weight, novelty_bonus, select_batch, selection_weight,
    source_cap,
)
from remixer.fatigue.state import FatigueModel


def test_weight_is_the_product_of_taste_rest_and_novelty():
    assert selection_weight(0.8, 0.25, 1.5) == pytest.approx(0.8 * 0.75 * 1.5)
    assert selection_weight(0.8, 1.0, 1.5) == 0.0
    assert selection_weight(-0.2, 0.0, 1.0) == 0.0


def test_novelty_bonus_decreases_with_exposure():
    assert novelty_bonus(0) == 1.5
    assert novelty_bonus(1) == 1.25
    assert novelty_bonus(99) == pytest.approx(1.005)


def test_source_cap_is_about_five_percent():
    assert source_cap(100) == 5
    assert source_cap(40) == 2
    assert source_cap(10) == 1
    assert source_cap(0) == 1


def test_candidate_weight_uses_stem_and_source_fatigue():
    m = FatigueModel()
    c = StemCandidate("s1", "songA", 1.0)
    w0 = candidate_weight(c, m, 0)
    m.tired({"source:songA": 1.0}, at_s=0)
    assert candidate_weight(c, m, 0) == pytest.approx(w0 * 0.4)
    m.tired({"stem:s1": 1.0}, at_s=0)
    assert candidate_weight(c, m, 0) == pytest.approx(w0 * 0.4 * 0.4)


def test_disliked_stem_or_source_is_never_selected():
    m = FatigueModel()
    m.down({"source:bad": 1.0}, at_s=0, direct=True)
    m.down({"stem:x": 1.0}, at_s=0, direct=True)
    cands = [StemCandidate("x", "ok", 1.0), StemCandidate("y", "bad", 1.0), StemCandidate("z", "ok2", 0.1)]
    assert [c.stem_id for c in select_batch(cands, 3, m, 0, random.Random(0))] == ["z"]


def test_only_confirmed_insights_affect_selection():
    m = FatigueModel()
    ins = Insight("i1", "songA", "v1", 30_000, 40_000, "skip 30-40 s")
    inside = StemCandidate("s1", "songA", 1.0, 32_000, 36_000)
    outside = StemCandidate("s2", "songA", 1.0, 50_000, 60_000)
    assert candidate_weight(inside, m, 0, insights=[ins]) > 0
    assert candidate_weight(inside, m, 0, insights=[answer(ins, "unsure")]) > 0
    assert candidate_weight(inside, m, 0, insights=[answer(ins, "no")]) > 0
    yes = answer(ins, "yes")
    assert candidate_weight(inside, m, 0, insights=[yes]) == 0
    assert candidate_weight(outside, m, 0, insights=[yes]) > 0
    assert candidate_weight(StemCandidate("s3", "songA", 1.0), m, 0, insights=[yes]) == 0


def test_rested_source_returns_to_full_weight():
    m = FatigueModel()
    c = StemCandidate("s1", "songA", 1.0)
    w0 = candidate_weight(c, m, 0)
    m.tired({"source:songA": 1.0}, at_s=0)
    assert candidate_weight(c, m, 90 * 86_400) == pytest.approx(w0, rel=1e-3)


def test_selection_frequency_follows_weights():
    m = FatigueModel()
    cands = [StemCandidate("hi", "a", 0.9), StemCandidate("lo", "b", 0.1)]
    rng = random.Random(1)
    first = Counter(select_batch(cands, 1, m, 0, rng, SelectionConfig(source_cap_fraction=1.0))[0].stem_id
                    for _ in range(4000))
    assert 0.85 < first["hi"] / 4000 < 0.95


def test_selection_is_reproducible_with_a_seed():
    m = FatigueModel()
    cands = [StemCandidate(f"s{i}", f"src{i % 30}", (i % 7 + 1) / 7) for i in range(300)]
    a = select_batch(cands, 60, m, 0, random.Random(5))
    b = select_batch(cands, 60, m, 0, random.Random(5))
    assert a == b and len(a) == 60


@settings(max_examples=60, deadline=None)
@given(n_sources=st.integers(1, 60), per_source=st.integers(1, 10), size=st.integers(1, 200),
       seed=st.integers(0, 10_000), frac=st.sampled_from([0.05, 0.1, 0.02]))
def test_batch_never_exceeds_per_source_cap(n_sources, per_source, size, seed, frac):
    rng = random.Random(seed)
    cands = [StemCandidate(f"{s}-{i}", f"src{s}", rng.random()) for s in range(n_sources) for i in range(per_source)]
    cfg = SelectionConfig(source_cap_fraction=frac)
    batch = select_batch(cands, size, FatigueModel(), 0, random.Random(seed), cfg)
    cap = source_cap(size, frac)
    assert len(batch) <= size
    assert len({c.stem_id for c in batch}) == len(batch)
    assert max(Counter(c.source_id for c in batch).values(), default=0) <= cap
    assert len(batch) == min(size, sum(min(cap, sum(1 for c in cands if c.source_id == f"src{s}" and c.taste_score > 0))
                                       for s in range(n_sources)))

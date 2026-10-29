import numpy as np

from remixer.planner.sampling import gumbel, ranked, slot_key, uid, uniforms


def test_uniforms_are_open_interval_and_well_spread():
    u = uniforms(slot_key("x"), np.arange(200_000, dtype=np.uint64))
    assert 0 < u.min() and u.max() < 1
    hist, _ = np.histogram(u, bins=20, range=(0, 1))
    assert hist.min() > 0.95 * 10_000 and hist.max() < 1.05 * 10_000


def test_gumbel_max_samples_proportionally_to_weight():
    weights = np.array([1.0, 2.0, 3.0, 4.0])
    uids = np.array([uid(f"stem-{i}") for i in range(4)], np.uint64)
    wins = np.zeros(4)
    for s in range(20_000):
        wins[np.argmax(np.log(weights) + gumbel(slot_key("slot", s), uids))] += 1
    np.testing.assert_allclose(wins / wins.sum(), weights / weights.sum(), atol=0.012)


def test_noise_depends_only_on_slot_and_stem():
    ids = np.array([uid(f"s{i}") for i in range(50)], np.uint64)
    g = gumbel(7, ids)
    np.testing.assert_array_equal(gumbel(7, ids[::-1]), g[::-1])
    np.testing.assert_array_equal(gumbel(7, ids[10:20]), g[10:20])
    assert not np.array_equal(gumbel(8, ids), g)


def test_ranked_breaks_ties_by_tiebreak():
    ids = np.array([5, 5, 5], np.uint64)          # identical noise
    order = ranked(1, ids, np.zeros(3), np.array([2, 0, 1]))
    assert order.tolist() == [1, 2, 0]

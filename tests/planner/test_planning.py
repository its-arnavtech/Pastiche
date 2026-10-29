"""Planning properties: reproducibility, compatibility and batch rules, insights, bans, diversity."""
import dataclasses
import math

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st
from planner_helpers import check_cap, check_recipe, library, make_planner

from remixer.fatigue.insights import Insight, answer
from remixer.fatigue.state import FatigueModel
from remixer.planner import InMemoryCatalog, PlannerConfig, Rest, SongBan, SoundBan, StemTypeBan, rest
from remixer.planner.model import ROLES

SETTINGS = settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
seeds = st.integers(0, 2**31)


def batch_bytes(batch):
    return [r.canonical_bytes for r in batch.recipes]


@SETTINGS
@given(seed=seeds, n=st.integers(1, 12), lib_seed=st.integers(0, 3))
def test_same_inputs_and_seed_give_byte_identical_recipes(seed, n, lib_seed):
    lib = library(250, lib_seed)
    a = make_planner(lib).plan_batch(n, seed)
    b = make_planner(lib).plan_batch(n, seed)
    shuffled = InMemoryCatalog(list(lib.stems())[::-1])
    c = make_planner(shuffled).plan_batch(n, seed)
    assert batch_bytes(a) == batch_bytes(b) == batch_bytes(c)
    assert a.batch_id == b.batch_id == c.batch_id


def test_different_seeds_give_different_recipes(lib):
    p = make_planner(lib)
    assert batch_bytes(p.plan_batch(5, 1)) != batch_bytes(p.plan_batch(5, 2))


@SETTINGS
@given(seed=seeds, n=st.integers(1, 30), lib_seed=st.integers(0, 3))
def test_every_recipe_obeys_compatibility_roles_windows_and_the_cap(seed, n, lib_seed):
    lib = library(250, lib_seed)
    p = make_planner(lib)
    batch = p.plan_batch(n, seed)
    for r in batch.recipes:
        check_recipe(p, lib, r)
        assert len(r.sections) == p.config.sections
    check_cap(batch.recipes, batch.slots)
    filled = sum(len(s.placements) for r in batch.recipes for s in r.sections)
    assert filled + batch.unfilled_slots == batch.slots


def test_cap_binds_when_one_song_dominates_taste(lib):
    favourite = lib.stems()[0].song_id
    p = make_planner(lib, taste=lambda s: 1.0 if s.startswith(favourite) else 0.01)
    batch = p.plan_batch(40, 3)          # 640 slots -> cap 32
    counts = check_cap(batch.recipes, batch.slots)
    assert counts[favourite] <= 32


def test_role_coverage_is_high_on_a_reasonable_library(lib):
    batch = make_planner(lib).plan_batch(50, 9)
    assert batch.unfilled_slots / batch.slots < 0.1


def insights_on(batch, confirmed: bool, n=6):
    out = []
    for r in batch.recipes:
        for p in r.placements:
            if len(out) < n and p.song_id not in {i.track_id for i in out}:
                out.append(Insight(f"ins-{p.song_id}", p.song_id, "v1", p.src_start_ms, p.src_end_ms, "h", confirmed,
                                   "yes" if confirmed else None))
    return out


@SETTINGS
@given(seed=seeds)
def test_unconfirmed_insights_have_no_effect(seed):
    lib = library(250, 2)
    base = make_planner(lib).plan_batch(8, seed)
    pending = insights_on(base, confirmed=False)
    variants = [pending, [answer(i, "no") for i in pending], [answer(i, "unsure") for i in pending]]
    for ins in variants:
        assert batch_bytes(make_planner(lib, insights=ins).plan_batch(8, seed)) == batch_bytes(base)


def test_confirmed_insights_are_respected(lib):
    base = make_planner(lib).plan_batch(8, 4)
    confirmed = insights_on(base, confirmed=True)
    p = make_planner(lib, insights=confirmed)
    batch = p.plan_batch(8, 4)
    assert batch_bytes(batch) != batch_bytes(base)
    for r in batch.recipes:
        check_recipe(p, lib, r, insights=confirmed)


exclusions = st.one_of(
    st.builds(SongBan, st.integers(0, 249).map(lambda i: f"song-{i:05d}")),
    st.builds(StemTypeBan, st.integers(0, 249).map(lambda i: f"song-{i:05d}"), st.sampled_from(ROLES)),
    st.tuples(st.integers(0, 900), st.floats(0.05, 0.4)),
)


@SETTINGS
@given(seed=seeds, raw=st.lists(exclusions, min_size=1, max_size=4))
def test_banned_items_never_appear_in_new_recipes(seed, raw):
    lib = library(250, 0)
    exs = [SoundBan.around(lib.stems()[x[0] % len(lib)].embedding, x[1]) if isinstance(x, tuple) else x for x in raw]
    p = make_planner(lib, exclusions=exs)
    banned = p.exclusions.banned_stems
    for e in exs:
        if isinstance(e, SongBan):
            assert {s.stem_id for s in lib.stems_of(e.song_id)} <= banned
        elif isinstance(e, SoundBan):
            c = np.asarray(e.center, np.float32)
            near = {s.stem_id for s in lib.stems() if 1 - float(s.embedding @ c) <= e.radius - 1e-6}
            assert near and near <= banned
    batch = p.plan_batch(10, seed)
    for r in batch.recipes:
        check_recipe(p, lib, r, banned=banned)


def test_disliked_stems_are_never_selected(lib):
    fm = FatigueModel()
    used = make_planner(lib).plan_batch(10, 5).recipes[0].sections[0].placements[0]
    fm.down({f"source:{used.song_id}": 1.0}, 0.0, direct=True)
    batch = make_planner(lib, fatigue=fm).plan_batch(10, 5)
    assert used.song_id not in {p.song_id for r in batch.recipes for p in r.placements}


def test_rest_lowers_weight_but_never_excludes(lib):
    p0 = make_planner(lib)
    song = p0.plan_batch(5, 1).recipes[0].sections[0].placements[0].song_id
    fm = FatigueModel()
    rest(fm, Rest(f"source:{song}"), at_s=0.0)
    p = make_planner(lib, fatigue=fm)
    stems = [p.index.pos[s.stem_id] for s in lib.stems_of(song)]
    for i in stems:
        assert math.isfinite(p.log_base[i]) and p.log_base[i] < p0.log_base[i]
    assert p.exclusions.allowed[stems].all()
    with pytest.raises(TypeError):
        p.exclusions.add(Rest(f"source:{song}"))


def coverage(planner, batches, n=10):
    ledger, seen, out = {}, set(), []
    for b in range(batches):
        batch = planner.plan_batch(n, 100 + b, ledger)
        ledger = batch.ledger
        seen |= {p.song_id for r in batch.recipes for p in r.placements}
        out.append(len(seen))
    return out


def test_coverage_grows_and_diversity_spreads_use():
    lib = library(400, 1)
    cov = coverage(make_planner(lib), 8)
    assert all(b > a for a, b in zip(cov, cov[1:])), cov
    flat = make_planner(lib, config=dataclasses.replace(PlannerConfig(), batch_diversity=0.0, history_diversity=0.0))
    assert cov[-1] > coverage(flat, 8)[-1]

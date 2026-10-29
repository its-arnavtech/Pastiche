import dataclasses

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from remixer.planner.compat import (
    DEFAULT_COMPAT, CandidateIndex, CompatConfig, Target, best_shift, camelot, camelot_distance, fit, key_id,
    positions, tempo_fit,
)
from remixer.planner.model import ROLES, key_name

from planner_helpers import library


@pytest.mark.parametrize("key, code", [("C major", (8, True)), ("A minor", (8, False)), ("G major", (9, True)),
                                       ("E minor", (9, False)), ("F major", (7, True)), ("B major", (1, True)),
                                       ("D minor", (7, False))])
def test_camelot_codes(key, code):
    assert camelot(key_id(key)) == code


def test_camelot_distance():
    C, Am, G, Fs = (key_id(k) for k in ("C major", "A minor", "G major", "F# major"))
    assert camelot_distance(C, C) == 0
    assert camelot_distance(C, Am) == 1           # relative minor
    assert camelot_distance(C, G) == 1            # adjacent on the wheel
    assert camelot_distance(C, Fs) == 6           # opposite


def test_best_shift_prefers_no_shift_then_small_shifts():
    assert best_shift(key_id("C major"), key_id("C major"), DEFAULT_COMPAT) == (0, 1.0)
    s, f = best_shift(key_id("D major"), key_id("C major"), DEFAULT_COMPAT)
    assert s == -2 and f == pytest.approx(0.8)
    assert best_shift(key_id("F# major"), key_id("C major"), CompatConfig(max_shift=0)) is None


def test_tempo_fit_half_and_double_time():
    assert tempo_fit(120.0, 120.0, DEFAULT_COMPAT)[1:] == (1.0, 1.0)
    f, stretch, m = tempo_fit(174.0, 87.0, DEFAULT_COMPAT)
    assert (stretch, m) == (1.0, 0.5) and f == pytest.approx(DEFAULT_COMPAT.half_double_penalty)
    assert tempo_fit(64.0, 128.0, DEFAULT_COMPAT)[2] == 2.0
    assert tempo_fit(120.0, 131.0, DEFAULT_COMPAT) is None          # 9.2 percent
    assert tempo_fit(174.0, 87.0, CompatConfig(allow_half_double=False)) is None


def test_positions_are_on_the_downbeat_grid():
    stem = library(5).stems()[0]
    bar = stem.meter * 60_000 / stem.bpm
    ps = positions(stem, 10_000)
    assert ps and all(abs(p - (stem.downbeat_ms + round((p - stem.downbeat_ms) / bar) * bar)) <= 0.5 for p in ps)
    assert all(p + 10_000 <= stem.duration_ms for p in ps)
    assert positions(stem, stem.duration_ms + 1) == []


targets = st.builds(Target, tempo_bpm=st.floats(60, 190), key=st.sampled_from([key_name(p, m) for p in range(12)
                                                                                for m in (False, True)]),
                    meter=st.sampled_from([3, 4]), energy=st.floats(0, 1))


@settings(max_examples=60, deadline=None)
@given(target=targets, role=st.sampled_from(ROLES))
def test_vectorized_index_matches_scalar_reference(target, role):
    lib = library(300, seed=4)
    ix = CandidateIndex(lib.stems())
    idx, score, shift, stretch, mult = ix.query(role, target)
    got = {ix.ids[i]: (s, int(sh), st_, m) for i, s, sh, st_, m in zip(idx, score, shift, stretch, mult)}
    want = {}
    for stem in lib.stems():
        if stem.role == role and (f := fit(stem, target)) is not None:
            want[stem.stem_id] = (f.score, f.shift, f.stretch, f.multiplier)
    assert set(got) == set(want)
    for k, (s, sh, st_, m) in want.items():
        assert got[k][0] == pytest.approx(s, rel=1e-12) and got[k][1:] == (sh, pytest.approx(st_), m)


def test_index_ignores_catalog_order():
    stems = list(library(100).stems())
    a, b = CandidateIndex(stems), CandidateIndex(stems[::-1])
    t = Target(120.0, "A minor", 4, 0.6)
    for x, y in zip(a.query("bass", t), b.query("bass", t)):
        np.testing.assert_array_equal(x, y)


def test_config_is_respected():
    lib = library(300, seed=4)
    t = Target(120.0, "C major", 4, 0.6)
    wide = CandidateIndex(lib.stems(), dataclasses.replace(DEFAULT_COMPAT, max_stretch=0.2, energy_tolerance=1.0))
    narrow = CandidateIndex(lib.stems(), dataclasses.replace(DEFAULT_COMPAT, max_stretch=0.02, max_shift=0))
    assert len(wide.query("bass", t)[0]) > len(CandidateIndex(lib.stems()).query("bass", t)[0]) > \
        len(narrow.query("bass", t)[0])

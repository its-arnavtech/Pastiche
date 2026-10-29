import dataclasses

import pytest

from remixer.planner.model import Placement, Recipe, Section, changed_sections, key_name, parse_key


def placement(**kw):
    d = dict(stem_id="s1:bass", song_id="s1", role="bass", src_start_ms=4_000, src_end_ms=16_000,
             dst_start_ms=0, dst_end_ms=12_000, stretch=1.0, tempo_multiplier=1.0, shift_semitones=-2,
             gain_db=1.5, effects=(("reverb_mix", 0.15),))
    d.update(kw)
    return Placement(**d)


def section(i=0, placements=None, **kw):
    return Section(i, 0, 12_000, 120.0, "A minor", 4, 0.5, 7, tuple(placements or [placement()]), **kw)


def recipe(**kw):
    d = dict(sections=(section(0), section(1, [placement(stem_id="s2:bass", song_id="s2")])), seed=1,
             batch_id="b", batch_slots=8)
    d.update(kw)
    return Recipe(**d)


def test_canonical_bytes_are_stable_and_round_trip():
    a, b = recipe(), recipe()
    assert a.canonical_bytes == b.canonical_bytes and a.recipe_id == b.recipe_id
    back = Recipe.from_bytes(a.canonical_bytes)
    assert back == a and back.canonical_bytes == a.canonical_bytes


def test_float_noise_and_negative_zero_do_not_change_bytes():
    a = recipe(sections=(section(0, [placement(gain_db=0.0, stretch=1.0)]),))
    b = recipe(sections=(section(0, [placement(gain_db=-0.0, stretch=1.0 + 1e-12)]),))
    assert a.recipe_id == b.recipe_id


def test_any_content_change_changes_the_id():
    base = recipe()
    assert recipe(seed=2).recipe_id != base.recipe_id
    assert recipe(sections=(section(0, [placement(src_start_ms=4_001)]), base.sections[1])).recipe_id != base.recipe_id


def test_provenance_and_windows():
    r = recipe()
    assert r.songs == {"s1", "s2"} and r.stems == {"s1:bass", "s2:bass"}
    assert placement().windows == ("s1#0", "s1#1", "s1#2", "s1#3")  # 4.0 s - 16.0 s
    assert placement(src_start_ms=5_000, src_end_ms=10_000).windows == ("s1#1",)


def test_section_hash_ignores_nothing_in_the_section():
    s = section()
    assert dataclasses.replace(s, needs_regeneration=True).section_hash != s.section_hash
    assert dataclasses.replace(s, seed=8).section_hash != s.section_hash


def test_changed_sections():
    old = recipe()
    new = Recipe((old.sections[0], section(1, [placement(stem_id="s3:bass", song_id="s3")])), 1, "b", 8,
                 lineage_id=old.root_id, version=2, supersedes=old.recipe_id)
    assert changed_sections(old, new) == (1,)
    assert new.root_id == old.root_id != new.recipe_id


@pytest.mark.parametrize("bad", [
    lambda: placement(role="guitar"),
    lambda: placement(src_start_ms=5, src_end_ms=5),
    lambda: section(placements=[placement(), placement(stem_id="s9:bass", song_id="s9")]),
    lambda: section(placements=[placement(), placement(stem_id="s9:drums", song_id="s9", role="drums")]),
    lambda: recipe(version=2),
    lambda: recipe(sections=(section(1),)),
])
def test_invalid(bad):
    with pytest.raises(ValueError):
        bad()


def test_key_names():
    assert parse_key(key_name(1, True)) == (1, True)
    assert key_name(9, True) == "A minor"
    with pytest.raises(ValueError):
        parse_key("H dorian")

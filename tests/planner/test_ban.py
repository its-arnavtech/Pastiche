"""Ban-and-replace: minimal patches, untouched sections keep their hash, best replacement, no forcing."""
from collections import Counter

import numpy as np
import pytest
from hypothesis import HealthCheck, assume, given, settings, strategies as st
from planner_helpers import check_cap, check_recipe, library, make_planner, taste

from remixer.fatigue.selection import StemCandidate, candidate_weight, source_cap
from remixer.fatigue.state import FatigueModel
from remixer.planner import (
    InMemoryCatalog, InMemoryRecipeStore, LineageIndex, Rest, SongBan, SoundBan, StemMeta, StemTypeBan,
    plan_and_store,
)
from remixer.planner.compat import Target, fit, positions
from remixer.planner.plan import placement_windows

SETTINGS = settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def setup(lib, seed, batches=2, n=12, **kw):
    planner, store, lineage = make_planner(lib, **kw), InMemoryRecipeStore(), LineageIndex()
    for b in range(batches):
        plan_and_store(planner, n, seed + b, store, lineage)
    return planner, store, lineage


def make_exclusion(kind, lib, store, pick):
    used = sorted({(p.song_id, p.stem_id, p.role) for r in store.heads() for p in r.placements})
    song, stem, role = used[pick % len(used)]
    if kind == "song":
        return SongBan(song)
    if kind == "stem_type":
        return StemTypeBan(song, role)
    return SoundBan.around(lib.get(stem).embedding, 0.08)


@SETTINGS
@given(seed=st.integers(0, 2**31), kind=st.sampled_from(["song", "stem_type", "sound"]), pick=st.integers(0, 10**6))
def test_patch_is_minimal_correct_and_never_mutates(seed, kind, pick):
    lib = library(300, 3)
    planner, store, lineage = setup(lib, seed)
    before = {r.recipe_id: r.canonical_bytes for r in store.heads()}
    ex = make_exclusion(kind, lib, store, pick)
    patches = planner.ban(ex, store, lineage)
    banned = planner.exclusions.banned_stems

    expected = {rid for rid, b in before.items() if store.get(rid).stems & banned}
    assert {p.old_id for p in patches} == expected, "lineage must flag exactly the recipes containing the ban"
    for rid, b in before.items():
        assert store.get(rid).canonical_bytes == b, "stored versions are immutable"

    for patch in patches:
        old, new = store.get(patch.old_id), patch.new
        assert store.head(old.root_id).recipe_id == new.recipe_id
        assert (new.supersedes, new.version, new.root_id) == (old.recipe_id, old.version + 1, old.root_id)
        hit = {s.index for s in old.sections if s.stems & banned}
        assert set(patch.rerender) | set(patch.needs_regeneration) == hit
        assert not set(patch.rerender) & set(patch.needs_regeneration)
        for o, n in zip(old.sections, new.sections):
            if o.index in hit:
                kept = [p for p in o.placements if p.stem_id not in banned]
                assert all(p in n.placements for p in kept), "unbanned placements in a patched section stay"
            else:
                assert o.section_hash == n.section_hash, "untouched sections are provably unchanged"
        check_recipe(planner, lib, new, banned=banned)
        assert [r["section"] for r in patch.render_request()["sections"]] == list(patch.rerender)

    heads = list(store.heads())
    assert not any(r.stems & banned for r in heads)
    for batch_id in {r.batch_id for r in heads}:
        members = list(store.heads(batch_id))
        check_cap(members, members[0].batch_slots)
    for r in planner.plan_batch(10, seed + 99).recipes:
        check_recipe(planner, lib, r, banned=banned)


def brute_force_best(planner, lib, store, old, section_index, removed, banned):
    """Independent reimplementation of the replacement rule over the whole catalog."""
    c = planner.config
    sec = old.sections[section_index]
    target = Target(sec.tempo_bpm, sec.key, sec.meter, sec.energy)
    uses = Counter(p.song_id for r in store.heads(old.batch_id) for p in r.placements)
    uses[removed.song_id] -= 1
    cap = source_cap(old.batch_slots, c.selection.source_cap_fraction)
    forbid = set().union(*(s.windows for s in old.sections if s.index != section_index))
    ref = lib.get(removed.stem_id).embedding
    dst_len = removed.dst_end_ms - removed.dst_start_ms
    best = None
    for stem in lib.stems():
        if stem.role != removed.role or stem.stem_id in banned or uses[stem.song_id] >= cap:
            continue
        w = candidate_weight(StemCandidate(stem.stem_id, stem.song_id, taste(stem.stem_id)), FatigueModel(), 0.0)
        f = fit(stem, target, c.compat)
        if w <= 0 or f is None:
            continue
        src_len = int(round(dst_len * f.stretch))
        if not any(not (placement_windows(stem.song_id, s, s + src_len) & forbid) for s in positions(stem, src_len)):
            continue
        score = ((1 + float(stem.embedding @ ref)) / 2) ** c.replacement_similarity_power * f.score * w
        if best is None or score > best[0] * (1 + 1e-9):
            best = (score, stem.stem_id)
    return best


@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(seed=st.integers(0, 2**31), lib_seed=st.integers(0, 5), n_songs=st.integers(30, 120), pick=st.integers(0, 10**6))
def test_replacement_is_the_best_compatible_candidate(seed, lib_seed, n_songs, pick):
    lib = library(n_songs, lib_seed)
    planner, store, lineage = setup(lib, seed, batches=1, n=6)
    used = sorted({p.stem_id for r in store.heads() for p in r.placements})
    victim = lib.get(used[pick % len(used)])
    snapshot = InMemoryRecipeStore()
    for r in store.heads():
        snapshot.put(r)
    patches = planner.ban(StemTypeBan(victim.song_id, victim.role), store, lineage)
    first = patches[0]
    assume(len(first.replacements) == 1)
    rep = first.replacements[0]
    old = snapshot.get(first.old_id)
    removed = next(p for p in old.sections[rep.section].placements if p.stem_id == rep.removed)
    best = brute_force_best(planner, lib, snapshot, old, rep.section, removed, planner.exclusions.banned_stems)
    if best is None:
        assert rep.added is None and first.needs_regeneration == (rep.section,)
    else:
        assert rep.added is not None
        chosen = lib.get(rep.added)
        sec = old.sections[rep.section]
        f = fit(chosen, Target(sec.tempo_bpm, sec.key, sec.meter, sec.energy))
        w = candidate_weight(StemCandidate(chosen.stem_id, chosen.song_id, taste(chosen.stem_id)), FatigueModel(), 0.0)
        score = ((1 + float(chosen.embedding @ lib.get(removed.stem_id).embedding)) / 2) ** 4.0 * f.score * w
        assert score == pytest.approx(best[0], rel=1e-6)


def stem(song, role, bpm=120.0, key="A minor", vec=(1.0, 0.0, 0.0), energy=0.6):
    v = np.asarray(vec, np.float32)
    return StemMeta(f"{song}:{role}", song, role, bpm, key, 4, 0, -14.0, energy, 200_000, v / np.linalg.norm(v))


def test_no_acceptable_replacement_marks_needs_regeneration():
    stems = [stem("s1", "bass"), stem("s2", "drums", vec=(0, 1, 0)), stem("s4", "drums", vec=(0, 0, 1))]
    store, lineage = InMemoryRecipeStore(), LineageIndex()
    plan_and_store(make_planner(InMemoryCatalog(stems)), 1, 0, store, lineage)
    [old] = store.heads()
    assert "s1:bass" in old.stems
    off_tempo = stem("s3", "bass", bpm=150.0, vec=(0.9, 0.1, 0))   # the only other bass: 25 percent off tempo
    planner = make_planner(InMemoryCatalog(stems + [off_tempo]))
    [patch] = planner.ban(StemTypeBan("s1", "bass"), store, lineage)
    assert patch.rerender == () and patch.needs_regeneration
    for i in patch.needs_regeneration:
        sec = patch.new.sections[i]
        assert sec.needs_regeneration and "s1:bass" not in sec.stems
    assert patch.replacements and all(r.added is None for r in patch.replacements)


def test_partial_ban_keeps_the_songs_other_stems():
    lib = library(300, 3)
    planner, store, lineage = setup(lib, 5)
    song = next(iter(store.heads())).sections[0].placements[0].song_id
    planner.ban(StemTypeBan(song, "vocals"), store, lineage)
    for s in lib.stems_of(song):
        assert planner.exclusions.allowed[planner.index.pos[s.stem_id]] == (s.role != "vocals")


def test_bans_chain_versions_and_replay_deterministically():
    lib = library(300, 3)

    def run():
        planner, store, lineage = setup(lib, 11)
        top = Counter(p.song_id for r in store.heads() for p in r.placements).most_common(2)
        p1 = planner.ban(SongBan(top[0][0]), store, lineage)
        p2 = planner.ban(SongBan(top[1][0]), store, lineage)
        return store, [p.new.canonical_bytes for p in p1 + p2]

    store_a, a = run()
    _, b = run()
    assert a == b and a
    versions = max((store_a.versions(r.root_id) for r in store_a.heads()), key=len)
    assert [v.version for v in versions] == list(range(1, len(versions) + 1))
    for prev, nxt in zip(versions, versions[1:]):
        assert nxt.supersedes == prev.recipe_id


def test_rest_is_not_a_ban(world):
    planner, store, lineage = world
    with pytest.raises(TypeError):
        planner.ban(Rest("source:song-00001"), store, lineage)

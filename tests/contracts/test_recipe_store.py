"""RecipeStore and Lineage contracts (T-022): immutable versions, supersede chain, one-lookup lineage.

Every backend in ``RECIPE_BACKENDS`` must pass. Recipes come from the real planner on a small
synthetic library, version 2 from a real ban, so the stored shapes are the production ones.
"""
import dataclasses
import hashlib

import pytest

from remixer.fatigue.state import FatigueModel
from remixer.planner import InMemoryRecipeStore, LineageIndex, Planner, RecipeStoreError, SongBan
from remixer.planner.library import synthetic_library


def _taste(stem_id: str) -> float:
    return 0.2 + 0.8 * hashlib.sha256(stem_id.encode()).digest()[0] / 255


@pytest.fixture(scope="module")
def recipes():
    """Three version-1 recipes and, for the first, a version 2 from banning one of its songs."""
    lib = synthetic_library(150, seed=5)
    planner = Planner(lib, lib, _taste, FatigueModel(), 0.0)
    batch = planner.plan_batch(3, seed=1)
    store, lineage = InMemoryRecipeStore(), LineageIndex()
    for r in batch.recipes:
        store.put(r)
        lineage.add(r)
    v1 = batch.recipes[0]
    song = v1.sections[0].placements[0].song_id
    patches = {p.old_id: p.new for p in planner.ban(SongBan(song), store, lineage)}
    return batch.recipes, patches[v1.recipe_id], song


def test_put_get_round_trips_bytes_and_is_idempotent(open_recipes, recipes):
    store, _ = open_recipes()
    v1s, _, _ = recipes
    for r in v1s:
        assert store.put(r) == r.recipe_id
        assert store.put(r) == r.recipe_id
        got = store.get(r.recipe_id)
        assert got == r and got.canonical_bytes == r.canonical_bytes
    assert {h.recipe_id for h in store.heads()} == {r.recipe_id for r in v1s}


def test_only_version_one_can_be_put(open_recipes, recipes):
    store, _ = open_recipes()
    _, v2, _ = recipes
    with pytest.raises(RecipeStoreError):
        store.put(v2)


def test_supersede_chain_keeps_history(open_recipes, recipes):
    store, _ = open_recipes()
    v1s, v2, _ = recipes
    v1 = v1s[0]
    store.put(v1)
    assert store.supersede(v1.recipe_id, v2) == v2.recipe_id
    assert store.head(v1.root_id) == v2
    assert [r.recipe_id for r in store.versions(v1.root_id)] == [v1.recipe_id, v2.recipe_id]
    assert store.get(v1.recipe_id).canonical_bytes == v1.canonical_bytes


def test_supersede_rejects_anything_but_the_next_version_of_the_head(open_recipes, recipes):
    store, _ = open_recipes()
    v1s, v2, _ = recipes
    v1, other = v1s[0], v1s[1]
    for r in v1s:
        store.put(r)
    with pytest.raises(RecipeStoreError):
        store.supersede(other.recipe_id, v2)                      # wrong parent
    skip = dataclasses.replace(v2, version=3)
    with pytest.raises(RecipeStoreError):
        store.supersede(v1.recipe_id, skip)                       # version gap
    store.supersede(v1.recipe_id, v2)
    with pytest.raises(RecipeStoreError):
        store.supersede(v1.recipe_id, v2)                         # v1 is no longer the head
    with pytest.raises(KeyError):
        store.supersede("0" * 64, v2)


def test_heads_by_batch(open_recipes, recipes):
    store, _ = open_recipes()
    v1s, v2, _ = recipes
    for r in v1s:
        store.put(r)
    store.supersede(v1s[0].recipe_id, v2)
    assert {r.recipe_id for r in store.heads(v1s[0].batch_id)} == {v2.recipe_id} | {r.recipe_id for r in v1s[1:]}
    assert list(store.heads("no-such-batch")) == []


def test_unknown_id_raises_key_error(open_recipes):
    store, _ = open_recipes()
    with pytest.raises(KeyError):
        store.get("f" * 64)


def test_lineage_lookups_cover_song_stem_and_window(open_recipes, recipes):
    _, lineage = open_recipes()
    v1s, v2, song = recipes
    for r in [*v1s, v2]:
        lineage.add(r)
        lineage.add(r)                                            # idempotent
    v1 = v1s[0]
    with_song = {r.recipe_id for r in v1s if song in r.songs}
    assert lineage.containing(song=song) == with_song
    assert v1.recipe_id in with_song and song not in v2.songs
    assert lineage.containing(song=song, heads_only=True) == with_song - {v1.recipe_id}
    stem = next(iter(v2.stems))
    assert lineage.containing(stem=stem) == {r.recipe_id for r in [*v1s, v2] if stem in r.stems}
    window = next(iter(v2.windows))
    assert v2.recipe_id in lineage.containing(window=window)
    assert lineage.head(v1.root_id) == v2.recipe_id and lineage.is_head(v2.recipe_id)
    assert not lineage.is_head(v1.recipe_id) and not lineage.is_head("nope")
    assert lineage.containing(song="never-used") == frozenset()
    with pytest.raises(ValueError):
        lineage.containing(song=song, stem=stem)


def test_tenants_are_isolated(open_recipes, recipes):
    (store_a, lineage_a), (store_b, lineage_b) = open_recipes("tenant-a"), open_recipes("tenant-b")
    v1s, _, song = recipes
    store_a.put(v1s[0])
    lineage_a.add(v1s[0])
    with pytest.raises(KeyError):
        store_b.get(v1s[0].recipe_id)
    assert list(store_b.heads()) == []
    assert lineage_b.containing(song=song) == frozenset()
    assert open_recipes("tenant-a")[0].get(v1s[0].recipe_id) == v1s[0]


def test_recipe_ids_are_content_addressed_across_tenants(open_recipes, recipes):
    v1s, _, _ = recipes
    a, b = open_recipes("tenant-a")[0], open_recipes("tenant-b")[0]
    assert a.put(v1s[1]) == b.put(v1s[1]) == v1s[1].recipe_id

"""Catalog-backed planner adapters (T-023, T-025): stem catalog and neighbour queries from real catalog rows
and a real HNSW index, a planner run and ban on top, and track/tenant deletion.

The reference is the planner's ``InMemoryCatalog`` over the same stems: the adapter must answer every
query identically, since ``within`` feeds sound-level bans.
"""
import hashlib
import json

import numpy as np
import pytest

from remixer.adapters.planner_catalog import (SqliteLineage, SqliteRecipeStore, analysis_row, delete_tenant,
                                              delete_track, index_name, load_stem_catalog)
from remixer.fatigue.state import FatigueModel
from remixer.planner import Planner, SongBan, SoundBan
from remixer.planner.library import synthetic_library

pytest.importorskip("hnswlib")

VERSION = "clap-test@v2"
DIM = 32


def _taste(stem_id: str) -> float:
    return 0.2 + 0.8 * hashlib.sha256(stem_id.encode()).digest()[0] / 255


def load_library(a, lib) -> None:
    """Write a synthetic library the way ingest, separation, analysis and embedding would."""
    cat, idx = a.catalog, a.vector_index(index_name(VERSION), DIM)
    ids, vecs = [], []
    for s in lib.stems():
        cat.upsert("tracks", {"track_id": s.song_id, "synthetic": 1, "blob_key": f"tracks/{s.song_id}"}, key=["track_id"])
        cat.upsert("stems", {"stem_id": s.stem_id, "track_id": s.song_id, "stem_name": s.role, "model": "htdemucs",
                             "model_version": "4", "duration_s": s.duration_ms / 1000, "synthetic": 1,
                             "blob_key": f"stems/{s.stem_id}"}, key=["stem_id"])
        beats = [s.downbeat_ms / 1000 + i * 60 / s.bpm for i in range(8)]
        row = analysis_row(s.stem_id, "stem", {"bpm": s.bpm, "key": s.key, "lufs": s.loudness_lufs,
                                               "beat_positions": beats, "meter": s.meter,
                                               "duration_seconds": s.duration_ms / 1000}, "analysis-test")
        row["energy"] = json.dumps(s.energy)   # exact level, so planner inputs match the reference
        cat.upsert("analysis", row, key=["owner_id", "model_version"])
        rid = cat.insert("embeddings", {"owner_id": s.stem_id, "owner_kind": "stem", "model": "clap",
                                        "model_version": VERSION, "synthetic": 1})
        ids.append(rid)
        vecs.append(s.embedding)
    idx.add(ids, np.stack(vecs))
    idx.save()


@pytest.fixture(scope="module")
def lib():
    return synthetic_library(60, seed=7, dim=DIM)


@pytest.fixture
def loaded(open_tenant, lib):
    a = open_tenant("tenant-a")
    load_library(a, lib)
    return a, load_stem_catalog(a, dim=DIM)


def test_stem_catalog_matches_the_rows(loaded, lib):
    _, cat = loaded
    assert {s.stem_id for s in cat.stems()} == {s.stem_id for s in lib.stems()}
    for ref in lib.stems()[:20]:
        got = cat.get(ref.stem_id)
        assert (got.song_id, got.role, got.bpm, got.key, got.meter, got.downbeat_ms, got.duration_ms) == \
               (ref.song_id, ref.role, ref.bpm, ref.key, ref.meter, ref.downbeat_ms, ref.duration_ms)
        assert got.loudness_lufs == pytest.approx(ref.loudness_lufs) and got.energy == pytest.approx(ref.energy)
        assert float(got.embedding @ ref.embedding) == pytest.approx(1.0, abs=1e-5)
    song = lib.stems()[0].song_id
    assert {s.stem_id for s in cat.stems_of(song)} == {s.stem_id for s in lib.stems_of(song)}
    with pytest.raises(KeyError):
        cat.get("no-such-stem")


def test_nearest_is_ordered_best_first_with_stem_id_ties(loaded, lib):
    _, cat = loaded
    for probe in lib.stems()[:10]:
        got = cat.nearest(probe.embedding, 8)
        assert [sid for sid, _ in got] == [sid for sid, _ in lib.nearest(probe.embedding, 8)]
        sims = [s for _, s in got]
        assert sims == sorted(sims, reverse=True) and got[0][0] == probe.stem_id
        assert all(a[1] > b[1] or a[0] < b[0] for a, b in zip(got, got[1:]))


def test_within_contains_the_true_ball(loaded, lib):
    _, cat = loaded
    for probe in lib.stems()[:10]:
        for radius in (0.05, 0.2, 0.5):
            truth = set(lib.within(probe.embedding, radius))
            assert truth <= set(cat.within(probe.embedding, radius))


def test_planner_runs_and_bans_on_catalog_adapters(loaded):
    a, cat = loaded
    planner = Planner(cat, cat, _taste, FatigueModel(), 0.0)
    batch = planner.plan_batch(3, seed=2)
    store, lineage = SqliteRecipeStore(a.catalog), SqliteLineage(a.catalog)
    for r in batch.recipes:
        store.put(r)
        lineage.add(r)
    song = batch.recipes[0].sections[0].placements[0].song_id
    patches = planner.ban(SongBan(song), store, lineage)
    assert patches and all(song not in p.new.songs for p in patches)
    assert lineage.containing(song=song, heads_only=True) == frozenset()
    stem = batch.recipes[1].sections[0].placements[0].stem_id
    planner.ban(SoundBan.around(cat.get(stem).embedding, 0.05), store, lineage)
    assert lineage.containing(stem=stem, heads_only=True) == frozenset()


def test_tenants_see_only_their_stems(open_tenant, loaded):
    b = open_tenant("tenant-b")
    assert len(load_stem_catalog(b, dim=DIM).stems()) == 0


def test_delete_track_removes_derived_recipes_and_renders(loaded):
    a, cat = loaded
    planner = Planner(cat, cat, _taste, FatigueModel(), 0.0)
    store, lineage = SqliteRecipeStore(a.catalog), SqliteLineage(a.catalog)
    batch = planner.plan_batch(6, seed=3)
    for r in batch.recipes:
        store.put(r)
        lineage.add(r)
        a.catalog.insert("renders", {"render_id": "r-" + r.recipe_id, "recipe_id": r.recipe_id,
                                     "recipe_version": r.version, "blob_key": "renders/" + r.recipe_id})
    song = batch.recipes[0].sections[0].placements[0].song_id
    for p in planner.ban(SongBan(song), store, lineage):     # v2s no longer contain the song but derive from it
        a.catalog.insert("renders", {"render_id": "r-" + p.new.recipe_id, "recipe_id": p.new.recipe_id,
                                     "recipe_version": p.new.version})
    used = {r.recipe_id for r in batch.recipes if song in r.songs}
    roots = {store.get(rid).root_id for rid in used}
    doomed = {v.recipe_id for root in roots for v in store.versions(root)}
    keep = {r.root_id: [v.canonical_bytes for v in store.versions(r.root_id)]
            for r in batch.recipes if r.root_id not in roots}
    assert keep, "fixture needs an unaffected recipe"

    rep = delete_track(a.catalog, song)

    assert rep.recipes_removed == len(doomed) and rep.renders_removed == len(doomed)
    for rid in doomed:
        with pytest.raises(KeyError):
            store.get(rid)
        assert not lineage.is_head(rid)
    assert lineage.containing(song=song) == frozenset()
    left = a.catalog.query("SELECT recipe_id FROM renders")
    assert {r["recipe_id"] for r in left} == {v for root in keep for v in [x.recipe_id for x in store.versions(root)]}
    for root, blobs in keep.items():
        assert [v.canonical_bytes for v in store.versions(root)] == blobs
    assert a.catalog.query("SELECT 1 FROM stems WHERE track_id=?", (song,)) == []
    assert a.catalog.query("SELECT 1 FROM tracks WHERE track_id=?", (song,)) == []
    assert f"tracks/{song}" in rep.blob_keys and any(k.startswith("renders/") for k in rep.blob_keys)
    assert song not in {s.song_id for s in load_stem_catalog(a, dim=DIM).stems()}


def test_delete_tenant_leaves_other_tenants_untouched(open_tenant, loaded, lib):
    a, cat = loaded
    b = open_tenant("tenant-b")
    load_library(b, lib)
    planner = Planner(cat, cat, _taste, FatigueModel(), 0.0)
    store_a, store_b = SqliteRecipeStore(a.catalog), SqliteRecipeStore(b.catalog)
    r = planner.plan_batch(1, seed=4).recipes[0]
    store_a.put(r)
    store_b.put(r)
    rep = delete_tenant(a.catalog)
    assert rep.recipes_removed == 1 and rep.stems_removed == len(lib.stems())
    assert list(store_a.heads()) == [] and a.catalog.query("SELECT 1 FROM stems") == []
    assert store_b.get(r.recipe_id).canonical_bytes == r.canonical_bytes
    assert len(load_stem_catalog(b, dim=DIM).stems()) == len(lib.stems())

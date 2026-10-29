"""The real-use path (wrap-up item 4): a rating made in the player reaches fatigue and changes the next batch,
synthetic and real data never mix, and a scanned library folder is never modified."""
import copy
import hashlib
import json
import os
import stat
import time

import numpy as np
import pytest

from remixer.adapters import build
from remixer.adapters.planner_catalog import SqliteRecipeStore, analysis_row, index_name
from remixer.config import DEFAULT_PROFILE, Profile, compute_resources
from remixer.planner.library import synthetic_library
from remixer.planner.model import Placement, Recipe, Section
from remixer.product import (REAL, SYNTHETIC, OriginMixError, fatigue_model, make_planner, newest_taste_weights,
                             origin_catalog, playback_events, project_rating_events, track_origin)
from remixer.server.app import PlayerBackend

pytest.importorskip("hnswlib")

VERSION, DIM = "clap-test@v2", 32


@pytest.fixture
def tenant(tmp_path):
    raw = copy.deepcopy(DEFAULT_PROFILE)
    a = build(Profile(raw=raw, resources=compute_resources({}), data_dir=tmp_path / "data"))
    yield a
    a.catalog.close()


def taste_of(lib):
    return {s.stem_id: 0.2 + 0.8 * hashlib.sha256(s.stem_id.encode()).digest()[0] / 255 for s in lib.stems()}


def load(a, lib, real_songs=frozenset()):
    """Write a library the way ingest, separation, analysis and embedding would; ``real_songs`` are synthetic=0."""
    cat, idx = a.catalog, a.vector_index(index_name(VERSION), DIM)
    ids, vecs = [], []
    for s in lib.stems():
        syn = 0 if s.song_id in real_songs else 1
        cat.upsert("tracks", {"track_id": s.song_id, "synthetic": syn, "blob_key": f"tracks/{s.song_id}"}, key=["track_id"])
        cat.upsert("stems", {"stem_id": s.stem_id, "track_id": s.song_id, "stem_name": s.role, "model": "htdemucs",
                             "model_version": "4", "duration_s": s.duration_ms / 1000, "synthetic": syn,
                             "blob_key": f"stems/{s.stem_id}"}, key=["stem_id"])
        row = analysis_row(s.stem_id, "stem", {"bpm": s.bpm, "key": s.key, "lufs": s.loudness_lufs, "meter": s.meter,
                                               "beat_positions": [s.downbeat_ms / 1000 + i * 60 / s.bpm for i in range(8)],
                                               "duration_seconds": s.duration_ms / 1000}, "analysis-test")
        row["energy"] = json.dumps(s.energy)
        cat.upsert("analysis", row, key=["owner_id", "model_version"])
        ids.append(cat.insert("embeddings", {"owner_id": s.stem_id, "owner_kind": "stem", "model": "clap",
                                             "model_version": VERSION, "synthetic": syn}))
        vecs.append(s.embedding)
    idx.add(ids, np.stack(vecs))
    idx.save()


def rating(event_id, recipe, etype, stem=None, t=None, source_kind="generated"):
    ev = {"event_id": event_id, "session_id": "s1", "track_id": recipe.root_id, "track_version": recipe.recipe_id,
          "event_type": etype, "position_ms": 3000, "wall_time": int((t or time.time()) * 1000),
          "source_kind": source_kind, "client_info": {"seq": 1}}
    if stem:
        ev["payload"] = {"stem_id": stem}
    return ev


def test_player_rating_reaches_fatigue_and_changes_the_next_batch(tenant):
    lib = synthetic_library(80, seed=3, dim=DIM)
    load(tenant, lib)
    taste = taste_of(lib)
    now = time.time()
    planner, _ = make_planner(tenant, SYNTHETIC, taste, now, model_version=VERSION, dim=DIM)
    before = planner.plan_batch(3, 5)
    store = SqliteRecipeStore(tenant.catalog)
    for r in before.recipes:
        store.put(r)
    victim = next(p for p in before.recipes[0].placements if p.role != "drums")

    backend = PlayerBackend(tenant)
    n, errors = backend.append([rating("r1", before.recipes[0], "rate_down", victim.stem_id)])    # what the player posts
    assert (n, errors) == (1, [])

    rows = tenant.catalog.query("SELECT * FROM rating_events")
    assert [(r["event_id"], r["rating"], r["target_kind"], r["synthetic"]) for r in rows] == [("r1", "down", "track", 1)]
    fm, events = fatigue_model(tenant, SYNTHETIC)
    assert len(events) == 1 and fm.is_disliked(f"stem:{victim.stem_id}")

    planner2, _ = make_planner(tenant, SYNTHETIC, taste, now + 5, model_version=VERSION, dim=DIM, fatigue=fm)
    after = planner2.plan_batch(3, 5)
    stems_before = {p.stem_id for r in before.recipes for p in r.placements}
    stems_after = {p.stem_id for r in after.recipes for p in r.placements}
    assert victim.stem_id in stems_before and victim.stem_id not in stems_after
    assert stems_after != stems_before


def test_generated_track_rating_spreads_over_the_audible_stems(tenant):
    lib = synthetic_library(80, seed=3, dim=DIM)
    load(tenant, lib)
    now = time.time()
    planner, _ = make_planner(tenant, SYNTHETIC, taste_of(lib), now, model_version=VERSION, dim=DIM)
    r = planner.plan_batch(1, 9).recipes[0]
    SqliteRecipeStore(tenant.catalog).put(r)
    PlayerBackend(tenant).append([rating("r1", r, "rate_tired")])
    fm, _ = fatigue_model(tenant, SYNTHETIC)
    used = {p.stem_id for p in r.placements}
    tired = {s for s in used if fm.fatigue(f"stem:{s}", now + 5) > 0}
    assert tired == used                                                       # credited by loudness share
    assert not any(fm.is_disliked(f"stem:{s}") for s in used)                  # tired is temporary, never a ban


def test_synthetic_and_real_never_mix(tenant):
    lib = synthetic_library(60, seed=4, dim=DIM)
    songs = sorted({s.song_id for s in lib.stems()})
    real = frozenset(songs[:20])
    load(tenant, lib, real_songs=real)
    taste = taste_of(lib)
    now = time.time()

    syn_cat, real_cat = origin_catalog(tenant, SYNTHETIC, VERSION, DIM), origin_catalog(tenant, REAL, VERSION, DIM)
    assert {s.song_id for s in real_cat.stems()} <= real and not {s.song_id for s in syn_cat.stems()} & real
    assert len(real_cat) + len(syn_cat) == len(lib.stems())

    syn_planner, _ = make_planner(tenant, SYNTHETIC, taste, now, model_version=VERSION, dim=DIM)
    real_planner, _ = make_planner(tenant, REAL, taste, now, model_version=VERSION, dim=DIM)
    syn_r, real_r = syn_planner.plan_batch(1, 1).recipes[0], real_planner.plan_batch(1, 1).recipes[0]
    assert {p.song_id for p in real_r.placements} <= real and not {p.song_id for p in syn_r.placements} & real
    store = SqliteRecipeStore(tenant.catalog)
    store.put(syn_r)
    store.put(real_r)
    assert (track_origin(tenant, syn_r.root_id), track_origin(tenant, real_r.root_id)) == (SYNTHETIC, REAL)

    backend = PlayerBackend(tenant)
    backend.append([rating("syn-1", syn_r, "rate_down", syn_r.sections[0].placements[0].stem_id),
                    rating("real-1", real_r, "rate_up", t=now + 1)])
    flags = {r["event_id"]: r["synthetic"] for r in tenant.catalog.query("SELECT event_id, synthetic FROM rating_events")}
    assert flags == {"syn-1": 1, "real-1": 0}
    assert [e.event_id for e in playback_events(tenant, SYNTHETIC)] == ["syn-1"]
    assert [e.event_id for e in playback_events(tenant, REAL)] == ["real-1"]
    fm_real, _ = fatigue_model(tenant, REAL)
    assert not any(v.disliked for v in fm_real.states.values())               # the synthetic dislike is invisible to real
    assert fm_real.states and all(v.taste_evidence >= 0 for v in fm_real.states.values())

    # a recipe that uses songs of both origins is a bug and refuses to be classified
    a_stem = next(s for s in lib.stems() if s.song_id in real)
    b_stem = next(s for s in lib.stems() if s.song_id not in real and s.role != a_stem.role)
    pl = lambda s, d: Placement(s.stem_id, s.song_id, s.role, 0, 1000, d, d + 1000)   # noqa: E731
    mixed = Recipe((Section(0, 0, 2000, 120.0, "A minor", 4, 0.5, 1, (pl(a_stem, 0), pl(b_stem, 1000))),), 1, "b", 2)
    store.put(mixed)
    with pytest.raises(OriginMixError):
        track_origin(tenant, mixed.root_id)
    with pytest.raises(FileNotFoundError):
        newest_taste_weights(tenant, REAL)          # no real checkpoint exists: a real planner cannot borrow the synthetic one


def test_project_rating_events_is_idempotent(tenant):
    lib = synthetic_library(20, seed=1, dim=DIM)
    load(tenant, lib)
    s = lib.stems()[0]
    ev = {"event_id": "e1", "session_id": "s", "track_id": s.song_id, "track_version": "v1", "event_type": "rate_tired",
          "position_ms": 0, "wall_time": "2026-10-29T10:00:00Z", "source_kind": "source"}
    assert project_rating_events(tenant, [ev, ev]) == 2
    rows = tenant.catalog.query("SELECT * FROM rating_events")
    assert len(rows) == 1 and rows[0]["target_kind"] == "source" and rows[0]["synthetic"] == 1


def _snapshot(root):
    snap = {}
    for dirpath, dirs, files in os.walk(root):
        for name in sorted(dirs) + sorted(files):
            p = os.path.join(dirpath, name)
            st = os.stat(p)
            digest = hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.isfile(p) else None
            snap[os.path.relpath(p, root)] = (st.st_size, st.st_mtime_ns, digest, bool(st.st_mode & stat.S_IWRITE))
    return snap


def test_scanned_library_is_never_modified(tenant, tmp_path):
    import soundfile as sf

    from remixer.cpu.analyze import analyze_file
    from remixer.ingest import ingest_library

    lib = tmp_path / "Music"
    (lib / "Album").mkdir(parents=True)
    rng = np.random.default_rng(0)
    for i, d in enumerate((lib, lib, lib / "Album")):
        sf.write(d / f"song{i}.wav", (0.1 * rng.standard_normal((44100 * 3, 2))).astype(np.float32), 44100, subtype="PCM_16")
    (lib / "notes.txt").write_text("not audio")
    for p in lib.rglob("*"):
        if p.is_file():
            os.chmod(p, stat.S_IREAD)           # read-only: any write attempt would raise PermissionError on Windows
    before = _snapshot(lib)
    try:
        out = ingest_library(tenant, lib)
        for p in sorted(lib.rglob("*.wav")):
            analyze_file(p)                      # the analysis lane reads the same files in place
        again = ingest_library(tenant, lib)      # a second scan dedupes by content hash
        assert _snapshot(lib) == before          # contents, mtimes, sizes, permissions and the set of files
    finally:
        for p in lib.rglob("*"):
            if p.is_file():
                os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
    assert out["registered"] == 3 and again["registered"] == 3
    rows = tenant.catalog.query("SELECT track_id, source_path, synthetic, blob_key FROM tracks")
    assert len(rows) == 3 and all(r["synthetic"] == 0 and r["blob_key"] is None for r in rows)   # real origin, no copy made
    assert all(os.path.dirname(r["source_path"]).startswith(str(lib)) for r in rows)

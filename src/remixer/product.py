"""The product loop glue: analysis into the catalog, taste, ratings, fatigue and planning, with origin isolation.

Everything here sits between the lanes and the planner. It exists so one function call per step turns what the
lanes produced into the next batch of recipes:

- ``persist_analysis``: stems -> ``analysis`` rows (the planner reads these).
- ``project_rating_events``: the player's ``rate_*`` events -> ``rating_events`` rows, each tagged with its origin.
- ``fatigue_model``: replay the playback stream (ratings plus passive signals) into a ``FatigueModel``.
- ``make_planner``: planner over one origin's stems, that origin's taste and that origin's fatigue.

Origins: every track, stem, recipe and event belongs to exactly one of ``synthetic`` (generated corpus, demo,
simulated listening) or ``real`` (the owner's library). A recipe's origin is the origin of the songs it uses.
Synthetic and real data never mix (spec section 4 and AGENTS.md): each function takes an origin, drops the other
origin's rows, and raises ``OriginMixError`` where mixing would otherwise be silent.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

SYNTHETIC, REAL = "synthetic", "real"
ORIGINS = (SYNTHETIC, REAL)


class OriginMixError(ValueError):
    """Synthetic and real rows were about to be combined."""


def _origin_name(flag) -> str:
    return SYNTHETIC if flag else REAL


# ------------------------------------------------------------------ origins

def song_origins(a) -> dict[str, str]:
    return {r["track_id"]: _origin_name(r["synthetic"]) for r in a.catalog.query("SELECT track_id, synthetic FROM tracks")}


def stem_origins(a) -> dict[str, str]:
    return {r["stem_id"]: _origin_name(r["synthetic"]) for r in a.catalog.query("SELECT stem_id, synthetic FROM stems")}


def track_origin(a, track_id: str, _songs: dict[str, str] | None = None) -> str | None:
    """Origin of a source track, or of a generated track (a recipe root). ``None`` when unknown.

    A recipe built from songs of both origins is a bug, so it raises instead of picking one.
    """
    songs = _songs if _songs is not None else song_origins(a)
    if track_id in songs:
        return songs[track_id]
    from remixer.adapters.planner_catalog import SqliteRecipeStore

    try:
        head = SqliteRecipeStore(a.catalog).head(track_id)
    except KeyError:
        return None
    found = {songs.get(p.song_id) for p in head.placements}
    if len(found - {None}) > 1:
        raise OriginMixError(f"recipe {track_id[:12]} uses both synthetic and real songs")
    return next(iter(found - {None}), None)


# ------------------------------------------------------------------ analysis -> catalog

def persist_analysis(a, workers: int | None = None) -> dict:
    """Analyze every stem without an ``analysis`` row and store the result (the planner needs tempo, key, LUFS)."""
    from concurrent.futures import as_completed

    from remixer.adapters.planner_catalog import analysis_row
    from remixer.cpu.analyze import VERSION, _job, combine_stem_features
    from remixer.cpu.runtime import configured_workers, process_pool

    rows = a.catalog.query(
        "SELECT s.stem_id, s.track_id, s.stem_name, s.blob_key, s.synthetic FROM stems s LEFT JOIN analysis x "
        "ON x.owner_id = s.stem_id AND x.model_version = ? WHERE x.owner_id IS NULL ORDER BY s.stem_id", (VERSION,))
    root, t0 = a.profile.data_dir, time.perf_counter()
    n_workers = configured_workers(workers)
    results: dict[str, dict] = {}
    with process_pool(n_workers) as pool:
        futures = {pool.submit(_job, (str(root / r["blob_key"]), None, False,
                                      {"synthetic": bool(r["synthetic"]), "augmented": False,
                                       "real": not r["synthetic"]})): r for r in rows}
        for f in as_completed(futures):
            results[futures[f]["stem_id"]] = f.result()
    # Stems of one song share its tempo and key. A pad or a vocal line has no reliable pulse of its own, so the
    # song's tempo comes from its percussion and its key from its harmonic stem (cpu.analyze.combine_stem_features).
    by_song: dict[str, dict[str, dict]] = {}
    for r in rows:
        by_song.setdefault(r["track_id"], {})[r["stem_name"]] = results[r["stem_id"]]
    for r in rows:
        res = dict(results[r["stem_id"]])
        song = combine_stem_features(by_song[r["track_id"]])
        if song["bpm"] is not None:
            res["bpm"], res["beat_positions"] = song["bpm"], song["beat_positions"]
        if song["key"] is not None:
            res["key"] = song["key"]
        a.catalog.upsert("analysis", analysis_row(r["stem_id"], "stem", res, VERSION), key=["owner_id", "model_version"])
    return {"analyzed": len(rows), "workers": n_workers, "seconds": round(time.perf_counter() - t0, 1)}


# ------------------------------------------------------------------ taste

def newest_taste_weights(a, kind: str) -> Path:
    found = sorted((a.profile.data_dir / "models" / "taste").glob(f"taste-mlp-v1-{kind}-w*.npz"),
                   key=lambda p: p.stat().st_mtime)
    if not found:
        raise FileNotFoundError(f"no {kind} taste checkpoint: run `remixer taste{' --real' if kind == REAL else ''}`")
    return found[-1]


def stem_taste(a, origin: str, model_version: str) -> dict[str, float]:
    """Mean taste score of each stem's windows, from the ``origin`` checkpoint only."""
    from remixer.npu.trained import TasteWeights

    weights = TasteWeights.load(newest_taste_weights(a, origin))
    if weights.metadata["kind"] != origin:
        raise OriginMixError(f"{origin} planning given a {weights.metadata['kind']} taste checkpoint")
    if weights.metadata["embedding_model"] != model_version:
        raise ValueError("taste checkpoint was trained on a different embedding version")
    vec_root = a.profile.data_dir / "embeddings" / model_version.replace("@", "_").replace("/", "_")
    origins = stem_origins(a)
    out = {}
    for stem_id, o in origins.items():
        f = vec_root / f"{stem_id}.npy"
        if o == origin and f.exists():
            out[stem_id] = float(weights.predict(np.load(f).astype(np.float32)).mean())
    return out


# ------------------------------------------------------------------ ratings -> events -> fatigue

def _iso(ms: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000))


def project_rating_events(a, events: Iterable[dict]) -> int:
    """Store the player's ``rate_*`` events as ``rating_events`` rows, each tagged with its origin.

    Idempotent by ``event_id``. The row says what was rated (``target_kind`` source|track, ``target_id``) and
    whether it was synthetic. Window-level taste training reads only ``target_kind='window'`` rows, so these
    rows feed fatigue and never the taste model.
    """
    from remixer.analytics.events import parse_wall_time

    songs = song_origins(a)
    n = 0
    for e in events:
        if not str(e.get("event_type", "")).startswith("rate_"):
            continue
        origin = track_origin(a, e["track_id"], songs)
        a.catalog.upsert("rating_events", {
            "event_id": e["event_id"], "target_kind": "track" if e["source_kind"] == "generated" else "source",
            "target_id": e["track_id"], "rating": e["event_type"][5:], "window_start_ms": int(e["position_ms"]),
            "wall_time": _iso(parse_wall_time(e["wall_time"])),
            "synthetic": 1 if origin == SYNTHETIC else 0}, key=["event_id"])
        n += 1
    return n


def playback_events(a, origin: str):
    """The playback stream's events about ``origin`` tracks. Events about the other origin are dropped."""
    from remixer.analytics.events import Event

    songs = song_origins(a)
    cache: dict[str, str | None] = {}
    out = []
    for r in a.events.read("playback"):
        e = Event.from_row(r)
        if cache.setdefault(e.track_id, track_origin(a, e.track_id, songs)) == origin:
            out.append(e)
    return out


def event_origin_counts(a) -> dict[str, int]:
    songs, counts = song_origins(a), {SYNTHETIC: 0, REAL: 0, "unknown": 0}
    cache: dict[str, str | None] = {}
    for r in a.events.read("playback"):
        tid = r["track_id"]
        counts[cache.setdefault(tid, track_origin(a, tid, songs)) or "unknown"] += 1
    return counts


def recipe_lookup(a) -> Callable:
    """``(track_id, track_version) -> [StemUse]`` for credit assignment: a generated track's audible stems."""
    from remixer.adapters.planner_catalog import SqliteRecipeStore
    from remixer.fatigue.credit import StemUse

    store = SqliteRecipeStore(a.catalog)
    lufs = {r["owner_id"]: r["lufs"] for r in a.catalog.query("SELECT owner_id, lufs FROM analysis")}

    def lookup(track_id: str, track_version: str):
        try:
            r = store.get(track_version)
        except KeyError:
            return None
        return [StemUse(p.stem_id, p.song_id, p.dst_start_ms, p.dst_end_ms,
                        (lufs.get(p.stem_id) if lufs.get(p.stem_id) is not None else -23.0) + p.gain_db)
                for p in r.placements]

    return lookup


def fatigue_model(a, origin: str, neighbors=None):
    """Replay this origin's ratings and passive signals into a ``FatigueModel`` (state is always derived)."""
    from remixer.analytics.interpret import interpret
    from remixer.fatigue.state import replay

    events = playback_events(a, origin)
    return replay(events, recipes=recipe_lookup(a), signals=interpret(events).signals, neighbors=neighbors), events


def neighbor_lookup(catalog) -> Callable:
    """Fatigue propagation lookup over an ``InMemoryCatalog`` (embedding neighbours, similarity in [0, 1])."""
    def lookup(stem_id: str, k: int):
        try:
            v = catalog.get(stem_id).embedding
        except KeyError:
            return []
        return [(nid, max(0.0, s)) for nid, s in catalog.nearest(v, k + 1) if nid != stem_id][:k]

    return lookup


# ------------------------------------------------------------------ planning

def origin_catalog(a, origin: str, model_version: str | None = None, dim: int = 512):
    """The planner's stem catalog restricted to one origin."""
    from remixer.adapters.planner_catalog import load_stem_catalog
    from remixer.planner.catalog import InMemoryCatalog

    full = load_stem_catalog(a, model_version, dim)
    origins = stem_origins(a)
    return InMemoryCatalog([s for s in full.stems() if origins.get(s.stem_id) == origin])


def make_planner(a, origin: str, taste: dict[str, float], at_s: float, *, model_version: str | None = None,
                 dim: int = 512, exclusions=(), config=None, fatigue=None):
    """Planner over one origin: its stems, its taste scores, and fatigue replayed from its own events."""
    from remixer.planner.plan import DEFAULT_PLANNER, Planner

    cat = origin_catalog(a, origin, model_version, dim)
    if not len(cat):
        raise ValueError(f"no analyzed and embedded {origin} stems")
    if fatigue is None:
        fatigue, _ = fatigue_model(a, origin, neighbor_lookup(cat))
    mean = float(np.mean(list(taste.values()))) if taste else 0.5
    return Planner(cat, cat, lambda sid: taste.get(sid, mean), fatigue, at_s, exclusions=exclusions,
                   config=config or DEFAULT_PLANNER), cat


def stem_resolver(a) -> Callable[[str], Path]:
    root = a.profile.data_dir
    paths = {r["stem_id"]: root / r["blob_key"] for r in a.catalog.query("SELECT stem_id, blob_key FROM stems")}
    return paths.__getitem__


def render_and_register(a, recipe, cache_dir: Path, out_dir: Path, sample_rate: int = 22050) -> dict:
    """Full section-cached render of a recipe; the audio goes to the blob store and the catalog's ``renders``."""
    from remixer.cpu.patch_render import record_render, render_recipe

    out = out_dir / f"{recipe.recipe_id[:16]}.wav"
    manifest = render_recipe(recipe, stem_resolver(a), cache_dir, out, sample_rate=sample_rate)
    record_render(a.catalog, manifest, recipe.version, a.blobs.put_file(out, namespace="renders"))
    return manifest


def patch_and_register(a, patch, previous_manifest: dict, cache_dir: Path, out_dir: Path) -> dict:
    from remixer.cpu.patch_render import record_render, render_patch

    out = out_dir / f"{patch.new_id[:16]}.wav"
    manifest = render_patch(patch.render_request(), previous_manifest, stem_resolver(a), cache_dir, out)
    record_render(a.catalog, manifest, patch.new.version, a.blobs.put_file(out, namespace="renders"))
    return manifest

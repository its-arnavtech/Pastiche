"""Catalog-backed adapters for the planner Protocols (decision 0018, T-023 T-024 T-025).

- ``load_stem_catalog``: ``StemCatalog`` + ``NeighborQuery`` built from the ``stems``, ``analysis`` and
  ``embeddings`` rows, with stem vectors read back from the CLAP ``VectorIndex``. Neighbour queries
  are an exact scan of the stem matrix: tenant libraries are thousands of stems (about 1 ms per query)
  and ``within`` must never miss a stem a sound-level ban relies on. The HNSW index mixes stem and
  window vectors, so it serves as the vector store rather than the stem search structure.
- ``SqliteRecipeStore`` / ``SqliteLineage``: the planner's recipe store and lineage index in the
  tenant's catalog database (tables ``recipe_versions``, ``recipe_lineage``, ``recipe_refs``).
- ``delete_track`` / ``delete_tenant``: remove a song's derived data, or a whole tenant's.

Tenant scope is the catalog itself: the local profile has one catalog per tenant data directory.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterator

import numpy as np

from remixer.planner.catalog import InMemoryCatalog, StemMeta, unit
from remixer.planner.model import ROLES, Recipe, parse_key
from remixer.planner.store import RecipeStoreError

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipe_versions (
    recipe_id TEXT PRIMARY KEY, root_id TEXT NOT NULL, version INTEGER NOT NULL,
    supersedes TEXT, batch_id TEXT NOT NULL, bytes BLOB NOT NULL,
    UNIQUE (root_id, version)
);
CREATE TABLE IF NOT EXISTS recipe_lineage (
    recipe_id TEXT PRIMARY KEY, root_id TEXT NOT NULL, version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS recipe_refs (
    recipe_id TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL,   -- kind: song | stem | window
    PRIMARY KEY (kind, ref, recipe_id)
);
CREATE INDEX IF NOT EXISTS ix_recipe_versions_root ON recipe_versions(root_id, version);
CREATE INDEX IF NOT EXISTS ix_recipe_versions_batch ON recipe_versions(batch_id);
CREATE INDEX IF NOT EXISTS ix_recipe_lineage_root ON recipe_lineage(root_id, version);
CREATE INDEX IF NOT EXISTS ix_recipe_refs_recipe ON recipe_refs(recipe_id);
"""


def _ensure(catalog) -> None:
    if not getattr(catalog, "_planner_schema", False):
        catalog._con.executescript(SCHEMA)
        catalog._planner_schema = True


# ------------------------------------------------------------------ StemCatalog + NeighborQuery (T-023)

def index_name(model_version: str) -> str:
    """Same name the embedding worker uses (remixer.gpu.embed)."""
    return f"clap-{model_version.replace('@', '_').replace('/', '_')}"


def latest_embedding_version(catalog) -> str | None:
    rows = catalog.query("SELECT model_version, MAX(row_id) AS last FROM embeddings WHERE owner_kind='stem' "
                         "GROUP BY model_version ORDER BY last DESC LIMIT 1")
    return rows[0]["model_version"] if rows else None


def analysis_row(owner_id: str, owner_kind: str, result: dict[str, Any], model_version: str) -> dict[str, Any]:
    """Map one ``remixer.cpu.analyze`` result to an ``analysis`` row the stem catalog can read."""
    beats = [float(b) for b in result.get("beat_positions") or []]
    curve = [float(x) for x in result.get("energy_curve") or [] if x is not None]
    meta = {"meter": int(result.get("meter") or 4), "duration_ms": round(1000 * float(result.get("duration_seconds") or 0))}
    if beats:
        meta["downbeat_ms"] = round(1000 * beats[0])
    return {"owner_id": owner_id, "owner_kind": owner_kind, "model_version": model_version,
            "tempo": result.get("bpm"), "key": result.get("key"), "lufs": result.get("lufs"),
            "beats": json.dumps(beats), "energy": json.dumps(curve), "meta": json.dumps(meta)}


def _energy(raw: str | None) -> float:
    """Analysis stores the per-window RMS curve; the planner wants one 0..1 level (RMS -> dBFS over 60 dB)."""
    try:
        v = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return 0.5
    if isinstance(v, (int, float)):
        return float(min(1.0, max(0.0, v)))
    vals = [float(x) for x in v or [] if x]
    if not vals:
        return 0.5
    db = 20 * np.log10(max(statistics.fmean(vals), 1e-6))
    return float(min(1.0, max(0.0, (db + 60) / 60)))


def stem_metas(catalog, index, model_version: str) -> list[StemMeta]:
    """Every stem that has analysis and a stem-level embedding of ``model_version``. Others are skipped."""
    rows = catalog.query(
        "SELECT s.stem_id, s.track_id, s.stem_name, s.duration_s, a.tempo, a.key, a.lufs, a.beats, a.energy, "
        "a.meta, e.row_id FROM stems s "
        "JOIN analysis a ON a.owner_id = s.stem_id "
        "JOIN embeddings e ON e.owner_id = s.stem_id AND e.owner_kind = 'stem' AND e.model_version = ? "
        "ORDER BY s.stem_id, a.model_version DESC", (model_version,))
    seen, keep = set(), []
    for r in rows:
        if r["stem_id"] in seen or r["stem_name"] not in ROLES or not r["tempo"] or not r["key"]:
            continue
        try:
            parse_key(r["key"])
        except ValueError:
            continue
        seen.add(r["stem_id"])
        keep.append(r)
    if not keep:
        return []
    vecs = index.get([r["row_id"] for r in keep])
    out = []
    for r, v in zip(keep, vecs):
        meta = json.loads(r["meta"] or "{}")
        beats = json.loads(r["beats"] or "[]")
        out.append(StemMeta(
            stem_id=r["stem_id"], song_id=r["track_id"], role=r["stem_name"], bpm=float(r["tempo"]), key=r["key"],
            meter=int(meta.get("meter", 4)),
            downbeat_ms=int(meta.get("downbeat_ms", round(1000 * beats[0]) if beats else 0)),
            loudness_lufs=float(r["lufs"]) if r["lufs"] is not None else -23.0, energy=_energy(r["energy"]),
            duration_ms=int(meta.get("duration_ms") or round(1000 * (r["duration_s"] or 0))),
            embedding=unit(v)))
    return out


def load_stem_catalog(adapters, model_version: str | None = None, dim: int = 512) -> InMemoryCatalog:
    """A snapshot ``StemCatalog`` + ``NeighborQuery`` for this tenant. Reload to pick up new stems."""
    cat = adapters.catalog
    model_version = model_version or latest_embedding_version(cat)
    if model_version is None:
        return InMemoryCatalog([])
    return InMemoryCatalog(stem_metas(cat, adapters.vector_index(index_name(model_version), dim), model_version))


# ------------------------------------------------------------------ RecipeStore + Lineage (T-024)

class SqliteRecipeStore:
    """``planner.store.RecipeStore`` over the catalog: immutable canonical bytes keyed by recipe_id."""

    def __init__(self, catalog):
        self.cat = catalog
        _ensure(catalog)

    def _bytes(self, recipe_id: str) -> bytes:
        rows = self.cat.query("SELECT bytes FROM recipe_versions WHERE recipe_id=?", (recipe_id,))
        if not rows:
            raise KeyError(recipe_id)
        return bytes(rows[0]["bytes"])

    def __contains__(self, recipe_id: str) -> bool:
        return bool(self.cat.query("SELECT 1 FROM recipe_versions WHERE recipe_id=?", (recipe_id,)))

    def _insert(self, r: Recipe) -> None:
        self.cat.insert("recipe_versions", {"recipe_id": r.recipe_id, "root_id": r.root_id, "version": r.version,
                                            "supersedes": r.supersedes, "batch_id": r.batch_id,
                                            "bytes": r.canonical_bytes})

    def put(self, recipe: Recipe) -> str:
        if recipe.recipe_id in self:
            return recipe.recipe_id
        if recipe.version != 1:
            raise RecipeStoreError("only version 1 can be put; use supersede for later versions")
        self._insert(recipe)
        return recipe.recipe_id

    def get(self, recipe_id: str) -> Recipe:
        return Recipe.from_bytes(self._bytes(recipe_id))

    def _head_id(self, root_id: str) -> str:
        rows = self.cat.query("SELECT recipe_id FROM recipe_versions WHERE root_id=? ORDER BY version DESC LIMIT 1",
                              (root_id,))
        if not rows:
            raise KeyError(root_id)
        return rows[0]["recipe_id"]

    def supersede(self, old_id: str, new: Recipe) -> str:
        old = self.get(old_id)
        if self._head_id(old.root_id) != old_id:
            raise RecipeStoreError(f"{old_id[:12]} is not the head of its lineage")
        if new.supersedes != old_id or new.root_id != old.root_id or new.version != old.version + 1:
            raise RecipeStoreError("new version must supersede the head: same root, version + 1")
        self._insert(new)
        return new.recipe_id

    def head(self, root_id: str) -> Recipe:
        return self.get(self._head_id(root_id))

    def versions(self, root_id: str) -> list[Recipe]:
        rows = self.cat.query("SELECT bytes FROM recipe_versions WHERE root_id=? ORDER BY version", (root_id,))
        if not rows:
            raise KeyError(root_id)
        return [Recipe.from_bytes(bytes(r["bytes"])) for r in rows]

    def heads(self, batch_id: str | None = None) -> Iterator[Recipe]:
        sql = ("SELECT v.bytes FROM recipe_versions v JOIN (SELECT root_id, MAX(version) AS version FROM "
               "recipe_versions GROUP BY root_id) h ON h.root_id = v.root_id AND h.version = v.version")
        if batch_id is not None:
            # a lineage belongs to the batch its version 1 was planned in
            sql += " WHERE v.root_id IN (SELECT recipe_id FROM recipe_versions WHERE version = 1 AND batch_id = ?)"
        for r in self.cat.query(sql + " ORDER BY v.root_id", (batch_id,) if batch_id is not None else ()):
            yield Recipe.from_bytes(bytes(r["bytes"]))


class SqliteLineage:
    """``planner.lineage.Lineage`` over the catalog: one indexed lookup per song, stem or window."""

    def __init__(self, catalog):
        self.cat = catalog
        _ensure(catalog)

    def add(self, recipe: Recipe) -> None:
        rid = recipe.recipe_id
        if self.cat.query("SELECT 1 FROM recipe_lineage WHERE recipe_id=?", (rid,)):
            return
        refs = {("song", p.song_id) for p in recipe.placements} | {("stem", p.stem_id) for p in recipe.placements}
        refs |= {("window", w) for p in recipe.placements for w in p.windows}
        with self.cat._lock:
            con = self.cat._con
            con.execute("BEGIN IMMEDIATE")
            try:
                con.executemany("INSERT OR IGNORE INTO recipe_refs (recipe_id, kind, ref) VALUES (?, ?, ?)",
                                [(rid, k, ref) for k, ref in sorted(refs)])
                con.execute("INSERT INTO recipe_lineage (recipe_id, root_id, version) VALUES (?, ?, ?)",
                            (rid, recipe.root_id, recipe.version))
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise

    def containing(self, *, song: str | None = None, stem: str | None = None, window: str | None = None,
                   heads_only: bool = False) -> frozenset[str]:
        if sum(x is not None for x in (song, stem, window)) != 1:
            raise ValueError("give exactly one of song, stem, window")
        kind, ref = ("song", song) if song is not None else ("stem", stem) if stem is not None else ("window", window)
        rows = self.cat.query("SELECT recipe_id FROM recipe_refs WHERE kind=? AND ref=?", (kind, ref))
        hits = frozenset(r["recipe_id"] for r in rows)
        return frozenset(r for r in hits if self.is_head(r)) if heads_only else hits

    def head(self, root_id: str) -> str | None:
        rows = self.cat.query("SELECT recipe_id FROM recipe_lineage WHERE root_id=? ORDER BY version DESC LIMIT 1",
                              (root_id,))
        return rows[0]["recipe_id"] if rows else None

    def is_head(self, recipe_id: str) -> bool:
        rows = self.cat.query("SELECT root_id FROM recipe_lineage WHERE recipe_id=?", (recipe_id,))
        return bool(rows) and self.head(rows[0]["root_id"]) == recipe_id


# ------------------------------------------------------------------ deletion (T-025)

@dataclass
class DeletionReport:
    recipes_removed: int = 0
    renders_removed: int = 0
    stems_removed: int = 0
    embeddings_removed: int = 0
    events_removed: int = 0
    blob_keys: list[str] = field(default_factory=list)   # caller deletes these from the BlobStore


def _roots_containing(catalog, song_id: str) -> set[str]:
    rows = catalog.query(
        "SELECT DISTINCT root_id FROM recipe_lineage WHERE recipe_id IN "
        "(SELECT recipe_id FROM recipe_refs WHERE kind='song' AND ref=?) "
        "UNION SELECT DISTINCT root_id FROM recipe_versions WHERE recipe_id IN "
        "(SELECT recipe_id FROM recipe_refs WHERE kind='song' AND ref=?)", (song_id, song_id))
    return {r["root_id"] for r in rows}


def delete_track(catalog, song_id: str) -> DeletionReport:
    """Remove every recipe lineage any of whose versions used ``song_id`` (later versions derive from it
    even after a ban took the song out), their lineage rows and renders, the song's stems, analysis,
    windows and embedding rows, and its playback and rating events. Returns blob keys to delete."""
    _ensure(catalog)
    rep = DeletionReport()
    roots = sorted(_roots_containing(catalog, song_id))
    q = ",".join("?" * len(roots))
    stems = [r["stem_id"] for r in catalog.query("SELECT stem_id FROM stems WHERE track_id=?", (song_id,))]
    s = ",".join("?" * len(stems))
    with catalog._lock:
        con = catalog._con
        con.execute("BEGIN IMMEDIATE")
        try:
            if roots:
                ids = [r[0] for r in con.execute(
                    f"SELECT recipe_id FROM recipe_versions WHERE root_id IN ({q}) "
                    f"UNION SELECT recipe_id FROM recipe_lineage WHERE root_id IN ({q})", roots + roots)]
                i = ",".join("?" * len(ids))
                rep.blob_keys += [r[0] for r in con.execute(
                    f"SELECT blob_key FROM renders WHERE recipe_id IN ({i}) AND blob_key IS NOT NULL", ids)]
                rep.renders_removed = con.execute(f"DELETE FROM renders WHERE recipe_id IN ({i})", ids).rowcount
                con.execute(f"DELETE FROM recipe_refs WHERE recipe_id IN ({i})", ids)
                con.execute(f"DELETE FROM recipe_lineage WHERE recipe_id IN ({i})", ids)
                rep.recipes_removed = con.execute(f"DELETE FROM recipe_versions WHERE recipe_id IN ({i})", ids).rowcount
                con.execute(f"DELETE FROM stem_exposure WHERE recipe_id IN ({i})", ids)
                rep.events_removed += con.execute(
                    f"DELETE FROM playback_events WHERE track_id IN ({q}) OR track_version IN ({i})", roots + ids).rowcount
            if stems:
                win = [r[0] for r in con.execute(f"SELECT window_id FROM windows WHERE owner_id IN ({s})", stems)]
                owners = stems + win
                o = ",".join("?" * len(owners))
                rep.embeddings_removed = con.execute(f"DELETE FROM embeddings WHERE owner_id IN ({o})", owners).rowcount
                con.execute(f"DELETE FROM windows WHERE owner_id IN ({s})", stems)
                con.execute(f"DELETE FROM analysis WHERE owner_id IN ({s})", stems)
                con.execute(f"DELETE FROM stem_exposure WHERE stem_id IN ({s})", stems)
                con.execute(f"DELETE FROM stem_fatigue WHERE stem_id IN ({s})", stems)
                rep.blob_keys += [r[0] for r in con.execute(
                    f"SELECT blob_key FROM stems WHERE stem_id IN ({s}) AND blob_key IS NOT NULL", stems)]
                rep.stems_removed = con.execute(f"DELETE FROM stems WHERE stem_id IN ({s})", stems).rowcount
            con.execute("DELETE FROM analysis WHERE owner_id=?", (song_id,))
            rep.events_removed += con.execute("DELETE FROM playback_events WHERE track_id=?", (song_id,)).rowcount
            rep.events_removed += con.execute("DELETE FROM rating_events WHERE target_id=?", (song_id,)).rowcount
            rep.blob_keys += [r[0] for r in con.execute(
                "SELECT blob_key FROM tracks WHERE track_id=? AND blob_key IS NOT NULL", (song_id,))]
            con.execute("DELETE FROM tracks WHERE track_id=?", (song_id,))
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    return rep


def delete_tenant(catalog) -> DeletionReport:
    """Remove everything in this tenant's catalog (the local profile keeps one catalog per tenant)."""
    _ensure(catalog)
    rep = DeletionReport()
    tables = [r["name"] for r in catalog.query("SELECT name FROM sqlite_master WHERE type='table' "
                                               "AND name NOT LIKE 'sqlite_%'")]
    with catalog._lock:
        con = catalog._con
        rep.blob_keys = [r[0] for t in ("tracks", "stems", "renders")
                         for r in con.execute(f"SELECT blob_key FROM {t} WHERE blob_key IS NOT NULL")]
        rep.recipes_removed = con.execute("SELECT COUNT(*) FROM recipe_versions").fetchone()[0]
        rep.renders_removed = con.execute("SELECT COUNT(*) FROM renders").fetchone()[0]
        rep.stems_removed = con.execute("SELECT COUNT(*) FROM stems").fetchone()[0]
        rep.embeddings_removed = con.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        con.execute("BEGIN IMMEDIATE")
        try:
            for t in tables:
                con.execute(f"DELETE FROM {t}")
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    return rep

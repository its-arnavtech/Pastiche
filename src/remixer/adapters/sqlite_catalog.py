"""SQLite Catalog (spec section 9). WAL mode so many processes can read while one writes."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Sequence

from remixer.interfaces import Catalog

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    track_id TEXT PRIMARY KEY,          -- content hash of the source audio
    source_path TEXT, title TEXT, artist TEXT, album TEXT,
    duration_s REAL, sample_rate INTEGER, channels INTEGER,
    blob_key TEXT,
    synthetic INTEGER NOT NULL DEFAULT 0,
    augmented INTEGER NOT NULL DEFAULT 0,
    parent_track_id TEXT,               -- for augmented variants
    meta TEXT, created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS stems (
    stem_id TEXT PRIMARY KEY,           -- hash(track_id, model, stem_name)
    track_id TEXT NOT NULL REFERENCES tracks(track_id),
    stem_name TEXT NOT NULL,            -- drums | bass | vocals | other
    model TEXT NOT NULL, model_version TEXT NOT NULL,
    blob_key TEXT, duration_s REAL, rms REAL,
    synthetic INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (track_id, stem_name, model, model_version)
);
CREATE TABLE IF NOT EXISTS windows (
    window_id TEXT PRIMARY KEY,         -- hash(stem_id or track_id, start_ms)
    owner_id TEXT NOT NULL,             -- stem_id or track_id
    owner_kind TEXT NOT NULL,           -- stem | track
    start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
    features TEXT,                      -- JSON
    embedding_row INTEGER,              -- id in the vector index
    model_version TEXT,
    UNIQUE (owner_id, start_ms, model_version)
);
CREATE TABLE IF NOT EXISTS analysis (
    owner_id TEXT NOT NULL, owner_kind TEXT NOT NULL, model_version TEXT NOT NULL,
    tempo REAL, key TEXT, lufs REAL, beats TEXT, energy TEXT, meta TEXT,
    PRIMARY KEY (owner_id, model_version)
);
CREATE TABLE IF NOT EXISTS embeddings (
    row_id INTEGER PRIMARY KEY,         -- id in the vector index
    owner_id TEXT NOT NULL, owner_kind TEXT NOT NULL,   -- stem | window
    model TEXT NOT NULL, model_version TEXT NOT NULL,
    synthetic INTEGER NOT NULL DEFAULT 0,
    UNIQUE (owner_id, model, model_version)
);
CREATE TABLE IF NOT EXISTS recipes (
    recipe_id TEXT PRIMARY KEY, version INTEGER NOT NULL DEFAULT 1,
    tempo REAL, key TEXT, seed INTEGER, effects TEXT, spec TEXT,
    flagged INTEGER NOT NULL DEFAULT 0, synthetic INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS recipe_stems (
    recipe_id TEXT NOT NULL REFERENCES recipes(recipe_id),
    stem_id TEXT NOT NULL REFERENCES stems(stem_id),
    src_start_ms INTEGER, src_end_ms INTEGER, dst_start_ms INTEGER,
    stretch REAL, shift_semitones REAL, gain_db REAL,
    PRIMARY KEY (recipe_id, stem_id, dst_start_ms)
);
CREATE TABLE IF NOT EXISTS renders (
    render_id TEXT PRIMARY KEY, recipe_id TEXT NOT NULL, recipe_version INTEGER NOT NULL,
    blob_key TEXT, duration_s REAL, renderer_version TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS rating_events (
    event_id TEXT PRIMARY KEY, target_kind TEXT NOT NULL, target_id TEXT NOT NULL,
    rating TEXT NOT NULL,               -- up | down | tired
    window_start_ms INTEGER, wall_time TEXT NOT NULL,
    synthetic INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS playback_events (
    event_id TEXT PRIMARY KEY, session_id TEXT, track_id TEXT, track_version INTEGER,
    event_type TEXT, position_ms INTEGER, wall_time TEXT, source_kind TEXT, client_info TEXT,
    synthetic INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS stem_exposure (
    stem_id TEXT NOT NULL, recipe_id TEXT NOT NULL, exposed_at TEXT NOT NULL, loudness_share REAL,
    PRIMARY KEY (stem_id, recipe_id, exposed_at)
);
CREATE TABLE IF NOT EXISTS stem_fatigue (     -- derived; recomputed from events
    stem_id TEXT PRIMARY KEY, fatigue REAL NOT NULL, computed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS insights (
    insight_id TEXT PRIMARY KEY, track_id TEXT, window_start_ms INTEGER,
    hypothesis TEXT, skeptic TEXT, narrative TEXT, status TEXT DEFAULT 'pending',
    answer TEXT, created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_stems_track ON stems(track_id);
CREATE INDEX IF NOT EXISTS ix_windows_owner ON windows(owner_id);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=60, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA busy_timeout=60000")
    return con


class SqliteCatalog(Catalog):
    def __init__(self, path: Path):
        self.path = Path(path)
        self._con = connect(self.path)
        self._lock = threading.Lock()
        self._con.executescript(SCHEMA)

    def upsert(self, table: str, row: dict[str, Any], key: Sequence[str]) -> None:
        cols = list(row)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in key) or f"{key[0]}={key[0]}"
        sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
               f"ON CONFLICT ({', '.join(key)}) DO UPDATE SET {updates}")
        with self._lock:
            self._con.execute(sql, [row[c] for c in cols])

    def insert(self, table: str, row: dict[str, Any]) -> int:
        cols = list(row)
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
        with self._lock:
            return self._con.execute(sql, [row[c] for c in cols]).lastrowid

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._con.execute(sql, params).fetchall()]

    def get(self, table: str, **where: Any) -> dict[str, Any] | None:
        cond = " AND ".join(f"{k}=?" for k in where) or "1=1"
        rows = self.query(f"SELECT * FROM {table} WHERE {cond} LIMIT 1", list(where.values()))
        return rows[0] if rows else None

    def close(self) -> None:
        self._con.close()

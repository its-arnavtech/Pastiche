"""Durable SQLite job queue: idempotent enqueue, leases with expiry, retries.

A worker killed mid-job never acks; its lease expires and the job is leased again,
so a forced kill loses at most the in-flight item's progress.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from remixer.adapters.sqlite_catalog import connect
from remixer.interfaces import Job, JobQueue

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    priority INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued',   -- queued | leased | done | failed
    lease_owner TEXT, lease_until REAL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    result TEXT, error TEXT,
    created_at REAL NOT NULL, updated_at REAL NOT NULL,
    UNIQUE (kind, key)
);
CREATE INDEX IF NOT EXISTS ix_jobs_ready ON jobs(kind, status, priority DESC, id);
"""


class SqliteJobQueue(JobQueue):
    def __init__(self, path: Path, max_attempts: int = 3):
        self.path = Path(path)
        self.max_attempts = max_attempts
        self._con = connect(self.path)
        self._con.executescript(SCHEMA)

    def enqueue(self, kind: str, key: str, payload: dict[str, Any] | None = None, priority: int = 0) -> bool:
        t = time.time()
        cur = self._con.execute(
            "INSERT OR IGNORE INTO jobs (kind, key, payload, priority, max_attempts, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kind, key, json.dumps(payload or {}), priority, self.max_attempts, t, t))
        return cur.rowcount == 1

    def enqueue_many(self, kind: str, items: list[tuple[str, dict[str, Any]]], priority: int = 0) -> int:
        t = time.time()
        con = self._con
        con.execute("BEGIN IMMEDIATE")
        try:
            n = 0
            for key, payload in items:
                n += con.execute(
                    "INSERT OR IGNORE INTO jobs (kind, key, payload, priority, max_attempts, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (kind, key, json.dumps(payload), priority, self.max_attempts, t, t)).rowcount
            con.execute("COMMIT")
            return n
        except BaseException:
            con.execute("ROLLBACK")
            raise

    def lease(self, kind: str, owner: str, n: int = 1, lease_s: float = 300.0) -> list[Job]:
        t = time.time()
        con = self._con
        con.execute("BEGIN IMMEDIATE")
        try:
            rows = con.execute(
                "SELECT id FROM jobs WHERE kind=? AND attempts < max_attempts AND "
                "(status='queued' OR (status='leased' AND lease_until < ?)) "
                "ORDER BY priority DESC, id LIMIT ?", (kind, t, n)).fetchall()
            ids = [r["id"] for r in rows]
            jobs = []
            for jid in ids:
                r = con.execute(
                    "UPDATE jobs SET status='leased', lease_owner=?, lease_until=?, attempts=attempts+1, "
                    "updated_at=? WHERE id=? RETURNING id, kind, key, payload, attempts",
                    (owner, t + lease_s, t, jid)).fetchone()
                jobs.append(Job(id=r["id"], kind=r["kind"], key=r["key"], payload=json.loads(r["payload"]),
                                attempts=r["attempts"], lease_owner=owner))
            con.execute("COMMIT")
            return jobs
        except BaseException:
            con.execute("ROLLBACK")
            raise

    def ack(self, job_id: int, result: dict[str, Any] | None = None) -> None:
        self._con.execute("UPDATE jobs SET status='done', result=?, lease_until=NULL, updated_at=? WHERE id=?",
                          (json.dumps(result or {}), time.time(), job_id))

    def fail(self, job_id: int, error: str, retry: bool = True) -> None:
        self._con.execute(
            "UPDATE jobs SET status=CASE WHEN ? AND attempts < max_attempts THEN 'queued' ELSE 'failed' END, "
            "error=?, lease_until=NULL, updated_at=? WHERE id=?",
            (1 if retry else 0, error[-4000:], time.time(), job_id))

    def extend(self, job_id: int, lease_s: float = 300.0) -> None:
        self._con.execute("UPDATE jobs SET lease_until=?, updated_at=? WHERE id=? AND status='leased'",
                          (time.time() + lease_s, time.time(), job_id))

    def counts(self, kind: str | None = None) -> dict[str, int]:
        sql = "SELECT status, COUNT(*) AS n FROM jobs" + (" WHERE kind=?" if kind else "") + " GROUP BY status"
        rows = self._con.execute(sql, (kind,) if kind else ()).fetchall()
        return {r["status"]: r["n"] for r in rows}

    def requeue_failed(self, kind: str) -> int:
        return self._con.execute("UPDATE jobs SET status='queued', attempts=0 WHERE kind=? AND status='failed'",
                                 (kind,)).rowcount

    def close(self) -> None:
        self._con.close()

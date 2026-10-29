"""Parquet EventSink: each append writes a new immutable part file; DuckDB reads them back."""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

import pyarrow as pa
import pyarrow.parquet as pq

from remixer.interfaces import EventSink


class ParquetEventSink(EventSink):
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def append(self, stream: str, events: Iterable[dict[str, Any]]) -> int:
        rows = list(events)
        if not rows:
            return 0
        d = self.root / stream
        d.mkdir(parents=True, exist_ok=True)
        name = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.parquet"
        tmp = d / f".{name}.tmp"
        pq.write_table(pa.Table.from_pylist(rows), tmp)
        os.replace(tmp, d / name)
        return len(rows)

    def read(self, stream: str, where: str | None = None) -> list[dict[str, Any]]:
        d = self.root / stream
        if not d.exists() or not any(d.glob("*.parquet")):
            return []
        import duckdb

        glob = (d / "*.parquet").as_posix()
        sql = f"SELECT * FROM read_parquet('{glob}', union_by_name=true)" + (f" WHERE {where}" if where else "")
        con = duckdb.connect()
        try:
            cur = con.execute(sql)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            con.close()

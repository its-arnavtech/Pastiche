"""Parquet + DuckDB event store path for large heatmap builds (needs the ``analytics`` extra).

Events are written as Parquet (``client_info``/``payload`` as JSON text). The build reads with
DuckDB, ordered by ``(session_id, wall_time, file_row_number)`` so append order breaks ties,
splits sessions across processes by ``hash(session_id) % workers`` and merges partial heatmaps.
Durations come from one DuckDB aggregate (``client_info.duration_ms``, else the latest
``track_end``), so per-event JSON is never parsed in Python.

Run: ``python -m remixer.analytics.scale --events 5000000``.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import tempfile
import time
from pathlib import Path
from typing import Iterable, Iterator

from .events import EVENT_FIELDS, Event
from .heatmap import HeatmapBuilder
from .interpret import DEFAULT_CONFIG, InterpretConfig, VersionKey
from .simulate import iter_sessions, make_library

_INT_FIELDS = ("position_ms", "wall_time")
_JSON_FIELDS = ("client_info", "payload")


def _schema():
    import pyarrow as pa
    return pa.schema([(f, pa.int64() if f in _INT_FIELDS else pa.string()) for f in EVENT_FIELDS])


def write_events_parquet(batches: Iterable[list[Event]], path: Path, rows_per_group: int = 500_000) -> int:
    """Write event batches to one Parquet file; returns the row count."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = _schema()
    n = 0
    buf: dict[str, list] = {f: [] for f in EVENT_FIELDS}
    with pq.ParquetWriter(str(path), schema, compression="zstd") as w:
        def flush():
            w.write_table(pa.table(buf, schema=schema))
            for v in buf.values():
                v.clear()

        for batch in batches:
            for e in batch:
                d = e.to_dict()
                for f in EVENT_FIELDS:
                    v = d[f]
                    buf[f].append(json.dumps(v, separators=(",", ":")) if f in _JSON_FIELDS else v)
            n += len(batch)
            if len(buf["event_id"]) >= rows_per_group:
                flush()
        if buf["event_id"]:
            flush()
    return n


def durations_from_parquet(path: Path) -> dict[VersionKey, int]:
    import duckdb

    con = duckdb.connect()
    rows = con.execute(
        """
        SELECT track_id, track_version,
               coalesce(max(TRY_CAST(json_extract(client_info, '$.duration_ms') AS BIGINT)),
                        max(CASE WHEN event_type = 'track_end' THEN position_ms END))
        FROM read_parquet(?) GROUP BY ALL
        """, [str(path)]).fetchall()
    return {(t, v): int(d) for t, v, d in rows if d}


def iter_parquet_sessions(path: Path, part: int = 0, parts: int = 1,
                          batch_rows: int = 200_000) -> Iterator[list[Event]]:
    """Sessions of one hash partition, each as a wall-time ordered list (JSON columns skipped)."""
    import duckdb

    con = duckdb.connect()
    con.execute("SET threads TO 1")
    where = "WHERE hash(session_id) % ? = ?" if parts > 1 else ""
    params = [str(path)] + ([parts, part] if parts > 1 else [])
    rel = con.sql(
        f"""
        SELECT event_id, session_id, track_id, track_version, event_type, position_ms, wall_time,
               source_kind
        FROM read_parquet(?, file_row_number = true) {where}
        ORDER BY session_id, wall_time, file_row_number
        """, params=params)
    # duckdb >= 2.0 names it to_arrow_reader; 1.x has fetch_record_batch
    reader = (rel.to_arrow_reader if hasattr(rel, "to_arrow_reader") else rel.fetch_record_batch)(batch_rows)
    current: list[Event] = []
    sid = None
    for rb in reader:
        cols = rb.to_pydict()
        for row in zip(*(cols[c] for c in cols)):
            if row[1] != sid:
                if current:
                    yield current
                current, sid = [], row[1]
            current.append(Event(*row))
    if current:
        yield current


def _build_part(args) -> tuple[HeatmapBuilder, int]:
    path, part, parts, cfg, durations = args
    b = HeatmapBuilder(cfg)
    n = 0
    for session in iter_parquet_sessions(Path(path), part, parts):
        b.add_session(session, durations)
        n += len(session)
    return b, n


def build_heatmap_parquet(path: Path, cfg: InterpretConfig = DEFAULT_CONFIG,
                          workers: int | None = None) -> tuple[HeatmapBuilder, dict]:
    """Returns the merged heatmap and timings in seconds."""
    workers = workers or os.cpu_count() or 1
    t0 = time.perf_counter()
    durations = durations_from_parquet(path)
    t1 = time.perf_counter()
    jobs = [(str(path), i, workers, cfg, durations) for i in range(workers)]
    if workers == 1:
        results = [_build_part(jobs[0])]
    else:
        with mp.get_context("spawn").Pool(workers) as pool:
            results = pool.map(_build_part, jobs)
    merged = HeatmapBuilder(cfg)
    n = 0
    for b, k in results:
        merged.merge(b)
        n += k
    t2 = time.perf_counter()
    return merged, {"events": n, "durations_s": t1 - t0, "interpret_s": t2 - t1, "total_s": t2 - t0,
                    "workers": workers}


def write_heatmap_parquet(builder: HeatmapBuilder, path: Path) -> int:
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = builder.to_rows()
    pq.write_table(pa.Table.from_pylist(rows), str(path))
    return len(rows)


def run_scale(n_events: int, out_dir: Path, seed: int = 7, n_tracks: int = 2000,
              workers: int | None = None) -> dict:
    """Simulate ``n_events``, write Parquet, build the heatmap end to end; returns the numbers."""
    import random

    lib = make_library(n_tracks, random.Random(seed))
    path = out_dir / "events.parquet"

    def batches():
        total = 0
        for events in iter_sessions(lib, 10**9, seed + 1, listens={}):
            yield events
            total += len(events)
            if total >= n_events:
                return

    t0 = time.perf_counter()
    rows = write_events_parquet(batches(), path)
    t1 = time.perf_counter()
    builder, timing = build_heatmap_parquet(path, workers=workers)
    t2 = time.perf_counter()
    n_rows = write_heatmap_parquet(builder, out_dir / "heatmap.parquet")
    t3 = time.perf_counter()
    cand = builder.candidates()
    truth = {(t.track_id, t.track_version, w) for t in lib
             if builder.listens.get(t.key, 0) >= 3 for w in t.windows(t.disliked)}
    found = {(c.track_id, c.track_version, c.window_index) for c in cand}
    tp = len(found & truth)
    return {
        "events": rows, "parquet_mb": round(path.stat().st_size / 2**20, 1),
        "generate_and_write_s": round(t1 - t0, 2),
        "heatmap_build_s": round(t2 - t1, 2),
        "heatmap_durations_s": round(timing["durations_s"], 2),
        "heatmap_interpret_s": round(timing["interpret_s"], 2),
        "heatmap_write_s": round(t3 - t2, 2),
        "end_to_end_from_parquet_s": round(t3 - t1, 2),
        "events_per_s": round(rows / (t3 - t1)),
        "workers": timing["workers"], "listens": sum(builder.listens.values()),
        "heatmap_rows": n_rows, "candidates": len(cand),
        "precision": round(tp / len(found), 4) if found else 1.0,
        "recall": round(tp / len(truth), 4) if truth else 1.0,
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="End-to-end heatmap build timing on simulated events")
    ap.add_argument("--events", type=int, default=5_000_000)
    ap.add_argument("--tracks", type=int, default=2000)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=None, help="keep the Parquet files here")
    a = ap.parse_args(argv)
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        print(json.dumps(run_scale(a.events, a.out, a.seed, a.tracks, a.workers), indent=2))
    else:
        with tempfile.TemporaryDirectory() as d:
            print(json.dumps(run_scale(a.events, Path(d), a.seed, a.tracks, a.workers), indent=2))


if __name__ == "__main__":
    main()

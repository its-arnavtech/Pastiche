"""Stage 1, ingest: register tracks in the catalog (content hash = track_id) and enqueue GPU jobs.

Sources: the synthetic corpus (`<data>/corpus/*/track.json`, written by remixer.corpus) and,
optionally, a real music library, which is strictly read-only: it is hashed and read in place,
never modified, moved, uploaded or logged beyond its path.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from remixer.adapters.fs_blobstore import sha256_file

log = logging.getLogger("remixer.ingest")
AUDIO_EXT = {".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".aiff", ".aif", ".wma"}


def enqueue_separation(adapters, rows: list[dict], model: str | None = None) -> int:
    from remixer.gpu.separate import model_version

    model = model or adapters.profile["gpu"]["separation_model"]
    version = model_version(model)
    items = [(f"{r['track_id']}|{version}", {"track_id": r["track_id"], "path": r["source_path"]}) for r in rows]
    return adapters.jobs.enqueue_many(f"separate:{model}", items)


def ingest_corpus(adapters, corpus_dir: Path, enqueue: bool = True) -> dict:
    rows = []
    for tj in sorted(Path(corpus_dir).glob("*/track.json")):
        try:
            t = json.loads(tj.read_text(encoding="utf-8"))
            mix = Path(t["paths"]["mix"])
            if not mix.exists():
                continue
        except (json.JSONDecodeError, KeyError, OSError):
            continue  # being written right now; picked up on the next ingest
        row = {
            "track_id": t["hashes"]["mix"], "source_path": str(mix), "title": f"synthetic {t['track_id'][:8]}",
            "duration_s": t.get("duration"), "sample_rate": t.get("sample_rate"), "channels": 2,
            "synthetic": 1, "augmented": int(bool(t.get("augmented"))),
            "parent_track_id": t.get("parent_track_id"),
            "meta": json.dumps({k: t.get(k) for k in ("bpm", "key", "seed", "version", "track_id")}),
        }
        adapters.catalog.upsert("tracks", row, key=["track_id"])
        rows.append(row)
    n = enqueue_separation(adapters, rows) if enqueue else 0
    return {"registered": len(rows), "enqueued": n}


def ingest_library(adapters, library: Path, enqueue: bool = True) -> dict:
    """Read-only scan of a real library. Contents are never logged or modified."""
    import soundfile as sf

    rows = []
    for p in sorted(Path(library).rglob("*")):
        if p.suffix.lower() not in AUDIO_EXT or not p.is_file():
            continue
        try:
            tid = sha256_file(p)
        except OSError:
            continue
        if adapters.catalog.get("tracks", track_id=tid):
            rows.append({"track_id": tid, "source_path": str(p)})
            continue  # duplicate content: dedupe by hash
        dur = sr = ch = None
        try:
            info = sf.info(str(p))
            dur, sr, ch = info.duration, info.samplerate, info.channels
        except Exception:
            pass
        row = {"track_id": tid, "source_path": str(p), "title": p.stem, "duration_s": dur, "sample_rate": sr,
               "channels": ch, "synthetic": 0, "augmented": 0}
        adapters.catalog.upsert("tracks", row, key=["track_id"])
        rows.append(row)
    n = enqueue_separation(adapters, rows) if enqueue else 0
    return {"registered": len(rows), "enqueued": n}

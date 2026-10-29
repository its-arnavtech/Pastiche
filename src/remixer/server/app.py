"""Real player backend: FastAPI over the profile's adapters, serving the routes of decision 0016.

Same contract as ``web/mock_server.py`` (the player's test double), backed by real storage:

    GET  /api/config            project name and the events endpoint URL
    GET  /api/tracks            source tracks from the catalog (``tracks`` with audio) and rendered recipes
    GET  /audio/<track_id>.wav  the track's audio from the blob store, with HTTP Range support
    POST /api/events            append one event or a list to the ``playback`` stream (T-014 schema)
    GET  /api/events            that stream, in arrival order, exactly as posted
    GET  /api/ratings           rating state per track, derived from the stream
    GET  /api/insights          the passive inbox: the nightly job's InsightState (T-029) with the
                                user's answers from the stream applied

Events go to the ``EventSink`` (Parquet), where the nightly insight job reads them. The inbox is never
evaluated earlier than the night that produced it. Static files come from ``web/`` (no ``.py``, no
path escape). ``seed_demo`` loads the mock's demo tracks and seeded insights into a data directory so
the player's browser tests run unchanged against this backend.

Run: ``remixer serve --port 8765`` then open http://127.0.0.1:8765/.
"""
# No ``from __future__ import annotations``: FastAPI resolves the route signatures' ``Request`` annotations,
# which are imported lazily inside ``create_app`` so the CLI loads without the ``player`` extra.
import copy
import json
import threading
import time
from pathlib import Path
from typing import Any

from remixer.analytics.events import Event, validate_event
from remixer.config import REPO_ROOT

WEB_ROOT = REPO_ROOT / "web"
STREAM = "playback"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".json": "application/json"}


class PlayerBackend:
    """The backend's data side, independent of HTTP (the browser tests call it directly too)."""

    def __init__(self, adapters, events_url: str | None = None):
        self.a = adapters
        self.events_url = events_url
        self.lock = threading.Lock()

    # ---------------------------------------------------------------- config and tracks
    def config(self) -> dict:
        from remixer import PROJECT_NAME

        return {"project_name": PROJECT_NAME, "events_url": self.events_url or "/api/events", "seek_ms": 5000}

    def _tracks(self) -> list[dict]:
        out = []
        for r in self.a.catalog.query("SELECT track_id, title, artist, duration_s, blob_key, synthetic, meta "
                                      "FROM tracks WHERE blob_key IS NOT NULL ORDER BY created_at, track_id"):
            meta = json.loads(r["meta"] or "{}")
            out.append({"track_id": r["track_id"], "track_version": meta.get("track_version", "v1"),
                        "title": r["title"] or r["track_id"][:12], "artist": r["artist"] or "",
                        "source_kind": meta.get("source_kind", "source"),
                        "duration_ms": round(1000 * (r["duration_s"] or 0)), "blob_key": r["blob_key"],
                        "position": meta.get("position")})
        renders = self.a.catalog.query(
            "SELECT r.recipe_id, r.blob_key, r.duration_s, v.root_id FROM renders r "
            "JOIN recipe_versions v ON v.recipe_id = r.recipe_id WHERE r.blob_key IS NOT NULL "
            "AND v.version = (SELECT MAX(version) FROM recipe_versions w WHERE w.root_id = v.root_id) "
            "ORDER BY r.created_at, r.recipe_id") if self._has("recipe_versions") else []
        for r in renders:
            out.append({"track_id": r["root_id"], "track_version": r["recipe_id"],
                        "title": f"Recombined {r['root_id'][:6]}", "artist": "Remixer", "source_kind": "generated",
                        "duration_ms": round(1000 * (r["duration_s"] or 0)), "blob_key": r["blob_key"],
                        "position": None})
        return sorted(out, key=lambda t: (t["position"] is None, t["position"] or 0))

    def _has(self, table: str) -> bool:
        return bool(self.a.catalog.query("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)))

    def track_list(self) -> list[dict]:
        return [{k: t[k] for k in ("track_id", "track_version", "title", "artist", "source_kind", "duration_ms")}
                | {"audio_url": f"/audio/{t['track_id']}.wav"} for t in self._tracks()]

    def audio_path(self, track_id: str) -> Path | None:
        t = next((t for t in self._tracks() if t["track_id"] == track_id), None)
        return Path(self.a.blobs.path(t["blob_key"])) if t else None

    # ---------------------------------------------------------------- events
    def append(self, rows: list[dict]) -> tuple[int, list[str]]:
        errors = [f"event {i}: {e}" for i, r in enumerate(rows) for e in validate_event(r)]
        if errors:
            return 0, errors
        with self.lock:
            t = time.time_ns()
            self.a.events.append(STREAM, [Event.from_dict(r).to_row() | {"received_ns": t + i,
                                                                         "raw": json.dumps(r, separators=(",", ":"))}
                                          for i, r in enumerate(rows)])
            from remixer.product import project_rating_events

            project_rating_events(self.a, rows)   # ratings also land in rating_events, tagged with their origin
        return len(rows), []

    def events(self) -> list[dict]:
        rows = self.a.events.read(STREAM)
        rows.sort(key=lambda r: (r.get("received_ns") or 0))
        return [json.loads(r["raw"]) if r.get("raw") else Event.from_row(r).to_dict() for r in rows]

    def ratings(self) -> dict:
        out: dict[str, dict] = {}
        for e in sorted(self.events(), key=lambda e: e["wall_time"]):
            if not e["event_type"].startswith("rate_"):
                continue
            st = out.setdefault(e["track_id"], {"rating": None, "tired_at": None})
            kind = e["event_type"][5:]
            if kind in ("up", "down"):
                st["rating"] = kind
            elif kind == "clear":
                st["rating"] = None
            elif kind == "tired":
                st["tired_at"] = e["wall_time"]
        return out

    # ---------------------------------------------------------------- insights
    def insights(self, now_ms: int | None = None) -> list[dict]:
        from remixer.adapters.insight_job import _dir, load_state
        from remixer.insights import apply_answers, inbox_view
        from remixer.insights.evidence import local_day
        from remixer.insights.lifecycle import deliver

        state = copy.deepcopy(load_state(self.a))
        apply_answers(state, [Event.from_dict(e) for e in self.events() if e["event_type"].startswith("insight_")])
        last = _dir(self.a) / "last_run.json"
        as_of = json.loads(last.read_text(encoding="utf-8")).get("now_ms", 0) if last.exists() else 0
        state.records, _ = deliver(state.records, local_day(max(now_ms or int(time.time() * 1000), as_of), 0))
        titles = {t["track_id"]: t for t in self._tracks()}
        rows = inbox_view(state, titles)
        return sorted(rows, key=lambda x: (x["answer"] in ("yes", "no"), x["insight_id"]))


def create_app(backend: PlayerBackend):
    from fastapi import FastAPI, Request, Response
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    app = FastAPI(title="remixer player", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST", "OPTIONS"],
                       allow_headers=["Content-Type"])

    @app.middleware("http")
    async def no_store(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def js(obj, status: int = 200) -> JSONResponse:
        return JSONResponse(obj, status_code=status)

    @app.get("/api/config")
    def config():
        return js(backend.config())

    @app.get("/api/tracks")
    def tracks():
        return js(backend.track_list())

    @app.get("/api/events")
    def events():
        return js(backend.events())

    @app.get("/api/ratings")
    def ratings():
        return js(backend.ratings())

    @app.get("/api/insights")
    def insights():
        return js(backend.insights())

    @app.post("/api/events")
    async def post_events(request: Request):
        try:
            body = json.loads(await request.body() or b"null")
        except json.JSONDecodeError as e:
            return js({"error": f"bad json: {e}"}, 400)
        rows = body if isinstance(body, list) else [body]
        n, errors = backend.append(rows)
        return js({"accepted": n, "errors": errors}, 400 if errors else 200)

    @app.api_route("/audio/{name}", methods=["GET", "HEAD"])
    def audio(name: str, request: Request):
        path = backend.audio_path(name[:-4]) if name.endswith(".wav") else None
        if path is None or not path.exists():
            return js({"error": "no such track"}, 404)
        data = path.read_bytes()
        rng = request.headers.get("range")
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a) if a else max(0, len(data) - int(b))
            end = min(int(b) if (a and b) else len(data) - 1, len(data) - 1)
            if start >= len(data):
                return Response(status_code=416, media_type="audio/wav",
                                headers={"Content-Range": f"bytes */{len(data)}"})
            return Response(data[start:end + 1], status_code=206, media_type="audio/wav",
                            headers={"Accept-Ranges": "bytes", "Content-Range": f"bytes {start}-{end}/{len(data)}"})
        return Response(data, media_type="audio/wav", headers={"Accept-Ranges": "bytes"})

    @app.api_route("/{path:path}", methods=["GET", "HEAD"])
    def static(path: str):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (WEB_ROOT / rel).resolve()
        if WEB_ROOT not in target.parents or not target.is_file() or target.suffix == ".py":
            return js({"error": "not found"}, 404)
        return Response(target.read_bytes(), media_type=CONTENT_TYPES.get(target.suffix, "application/octet-stream"))

    return app


# ------------------------------------------------------------------ demo content and CLI

def _mock_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("remixer_web_mock", WEB_ROOT / "mock_server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def seed_demo(adapters) -> None:
    """The mock's four synthetic demo tracks (audio in the blob store, rows in the catalog) and its seeded
    insight state, written where the real job and backend keep them. Marked synthetic; never user audio."""
    from remixer.adapters.insight_job import _atomic_write, _dir

    mock = _mock_module()
    for i, t in enumerate(mock.MOCK_TRACKS):
        key = adapters.blobs.put(mock.synthesize(t), namespace="demo-audio", suffix=".wav")
        adapters.catalog.upsert("tracks", {
            "track_id": t["track_id"], "title": t["title"], "artist": t["artist"], "duration_s": t["duration_ms"] / 1000,
            "sample_rate": mock.SAMPLE_RATE, "channels": 1, "blob_key": key, "synthetic": 1,
            "meta": json.dumps({"position": i, "source_kind": t["source_kind"], "track_version": t["track_version"],
                                "demo": True})}, key=["track_id"])
    state, as_of = mock.MockBackend._seed_insights(None, 120)   # uses only module data, not the instance
    d = _dir(adapters)
    _atomic_write(d / "state.json", state.to_json())
    _atomic_write(d / "last_run.json", json.dumps({"day": "demo", "now_ms": as_of}))


def cmd_serve(args) -> int:
    import uvicorn

    from remixer.adapters import build

    a = build()
    if args.demo:
        seed_demo(a)
    print(f"player backend on http://{args.host}:{args.port}/ (events: {args.events_url or '/api/events'})")
    uvicorn.run(create_app(PlayerBackend(a, args.events_url)), host=args.host, port=args.port, log_level="warning")
    return 0


def register(sub) -> None:
    p = sub.add_parser("serve", help="player backend (FastAPI) over the profile's data")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--events-url", default=None, help="where the player posts events (default /api/events)")
    p.add_argument("--demo", action="store_true", help="load the synthetic demo tracks and insights first")
    p.set_defaults(fn=cmd_serve)

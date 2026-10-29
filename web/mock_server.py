"""Mock backend for the static player: stdlib only, for local use and headless tests.

Serves ``web/`` plus:

    GET  /api/config            project name and the events endpoint URL
    GET  /api/tracks            mock tracks (synthetic tones, no user audio)
    GET  /audio/<track_id>.wav  synthesized audio, with HTTP Range support for seeking
    POST /api/events            append one event or a list; each must pass the T-014 schema
    GET  /api/events            the append-only log (JSON lines on disk)
    GET  /api/ratings           persistent rating state per track, derived from the log
    GET  /api/insights          passive insights inbox with the user's answers applied

Insights come from the real detector run over a seeded synthetic history of the mock tracks
(``synthetic=true``, kept in memory, never written to the log).

Run: ``uv run python web/mock_server.py --port 8765`` then open http://127.0.0.1:8765/.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import sys
import threading
import wave
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

WEB_ROOT = Path(__file__).resolve().parent
REPO_ROOT = WEB_ROOT.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import remixer  # noqa: E402
from remixer.analytics.events import Event, validate_event  # noqa: E402
from remixer.analytics.heatmap import build_heatmap  # noqa: E402
from remixer.analytics.simulate import TrackSpec, iter_sessions  # noqa: E402
from remixer.fatigue.insights import apply_answer_events, insights_from_candidates  # noqa: E402

SAMPLE_RATE = 11_025
TIRED_VISIBLE_MS = 3 * 86_400_000

# Each track: 5-second sections, one chord root (semitones above A3) per section; "harsh" sections
# are the deliberately unpleasant parts that the seeded history skips.
MOCK_TRACKS = [
    {"track_id": "src-aurora", "track_version": "v1", "title": "Aurora", "artist": "Mock source",
     "source_kind": "source", "duration_ms": 45_000, "roots": [0, 5, 7, 0, 9, 5, 7, 0, 0], "harsh": [4, 5]},
    {"track_id": "gen-0001", "track_version": "r3f9c", "title": "Recombined #1", "artist": "Remixer",
     "source_kind": "generated", "duration_ms": 40_000, "roots": [2, 2, 7, 9, 2, 7, 9, 2], "harsh": [2]},
    {"track_id": "src-basalt", "track_version": "v1", "title": "Basalt", "artist": "Mock source",
     "source_kind": "source", "duration_ms": 35_000, "roots": [-5, 0, 2, -5, 0, 2, -5], "harsh": []},
    {"track_id": "gen-0002", "track_version": "r81aa", "title": "Recombined #2", "artist": "Remixer",
     "source_kind": "generated", "duration_ms": 50_000, "roots": [4, 4, 9, 11, 4, 9, 11, 4, 9, 4], "harsh": [6, 7]},
]


def track_spec(t: dict) -> TrackSpec:
    runs, start = [], None
    for w in range(len(t["roots"]) + 1):
        if w in t["harsh"] and start is None:
            start = w
        elif w not in t["harsh"] and start is not None:
            runs.append((start, w))
            start = None
    return TrackSpec(t["track_id"], t["track_version"], t["duration_ms"], t["source_kind"], tuple(runs))


def synthesize(t: dict) -> bytes:
    """Mono 16-bit WAV: soft triads per section, a buzzy square cluster in harsh sections."""
    n = int(SAMPLE_RATE * t["duration_ms"] / 1000)
    sec = SAMPLE_RATE * 5
    out = bytearray(n * 2)
    two_pi = 2 * math.pi
    for i in range(n):
        s = i // sec
        root = 220.0 * 2 ** (t["roots"][min(s, len(t["roots"]) - 1)] / 12)
        x = i / SAMPLE_RATE
        env = min(1.0, (i % sec) / 400, (sec - i % sec) / 400)
        if s in t["harsh"]:
            v = sum(1.0 if math.sin(two_pi * f * x) > 0 else -1.0 for f in (root * 2.01, root * 2.13)) * 0.12
        else:
            v = (math.sin(two_pi * root * x) + 0.6 * math.sin(two_pi * root * 1.26 * x)
                 + 0.5 * math.sin(two_pi * root * 1.5 * x)) * 0.18
        val = int(max(-1.0, min(1.0, v * env)) * 32_000)
        out[2 * i:2 * i + 2] = val.to_bytes(2, "little", signed=True)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(bytes(out))
    return buf.getvalue()


class MockBackend:
    def __init__(self, data_dir: Path, events_url: str | None = None, seed_sessions: int = 120):
        self.events_path = Path(data_dir) / "web-mock" / "events.jsonl"
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self.events_url = events_url
        self.lock = threading.Lock()
        self.audio: dict[str, bytes] = {}
        self.tracks = {t["track_id"]: t for t in MOCK_TRACKS}
        self.base_insights = self._seed_insights(seed_sessions)

    def _seed_insights(self, n_sessions: int):
        lib = [track_spec(t) for t in MOCK_TRACKS]
        history = [e for s in iter_sessions(lib, n_sessions, seed=7, tracks_per_session=(2, 4)) for e in s]
        return insights_from_candidates(build_heatmap(history).candidates())

    def config(self) -> dict:
        return {"project_name": getattr(remixer, "PROJECT_NAME", "remixer"),
                "events_url": self.events_url or "/api/events", "seek_ms": 5000}

    def track_list(self) -> list[dict]:
        return [{k: t[k] for k in ("track_id", "track_version", "title", "artist", "source_kind", "duration_ms")}
                | {"audio_url": f"/audio/{t['track_id']}.wav"} for t in MOCK_TRACKS]

    def wav(self, track_id: str) -> bytes | None:
        t = self.tracks.get(track_id)
        if t is None:
            return None
        with self.lock:
            if track_id not in self.audio:
                self.audio[track_id] = synthesize(t)
            return self.audio[track_id]

    def append(self, rows: list[dict]) -> tuple[int, list[str]]:
        errors = [f"event {i}: {e}" for i, r in enumerate(rows) for e in validate_event(r)]
        if errors:
            return 0, errors
        with self.lock, self.events_path.open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
        return len(rows), []

    def events(self) -> list[dict]:
        if not self.events_path.exists():
            return []
        with self.lock:
            lines = self.events_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(x) for x in lines if x.strip()]

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

    def insights(self) -> list[dict]:
        evs = [Event.from_dict(e) for e in self.events() if e["event_type"].startswith("insight_")]
        out = []
        for i in apply_answer_events(self.base_insights, evs):
            t = self.tracks.get(i.track_id, {})
            out.append({"insight_id": i.insight_id, "track_id": i.track_id, "track_version": i.track_version,
                        "title": t.get("title", i.track_id), "source_kind": t.get("source_kind", "source"),
                        "start_ms": i.start_ms, "end_ms": i.end_ms, "hypothesis": i.hypothesis,
                        "answer": i.answer, "confirmed": i.confirmed})
        return sorted(out, key=lambda x: (x["answer"] in ("yes", "no"), x["insight_id"]))


CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".json": "application/json"}


def make_handler(backend: MockBackend):
    class Handler(BaseHTTPRequestHandler):
        server_version = "remixer-mock/1"

        def log_message(self, fmt, *args):
            if os.environ.get("REMIXER_MOCK_LOG"):
                super().log_message(fmt, *args)

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, obj, status: int = 200):
            self._send(status, json.dumps(obj).encode(), "application/json")

        def do_OPTIONS(self):
            self.send_response(HTTPStatus.NO_CONTENT)
            self._cors()
            self.end_headers()

        def do_GET(self):
            path = urlparse(self.path).path
            routes = {"/api/config": backend.config, "/api/tracks": backend.track_list,
                      "/api/events": backend.events, "/api/ratings": backend.ratings,
                      "/api/insights": backend.insights}
            if path in routes:
                return self._json(routes[path]())
            if path.startswith("/audio/") and path.endswith(".wav"):
                return self._audio(path[len("/audio/"):-len(".wav")])
            return self._static(path)

        do_HEAD = do_GET

        def do_POST(self):
            if urlparse(self.path).path != "/api/events":
                return self._json({"error": "not found"}, 404)
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")
            except json.JSONDecodeError as e:
                return self._json({"error": f"bad json: {e}"}, 400)
            rows = body if isinstance(body, list) else [body]
            n, errors = backend.append(rows)
            return self._json({"accepted": n, "errors": errors}, 400 if errors else 200)

        def _audio(self, track_id: str):
            data = backend.wav(track_id)
            if data is None:
                return self._json({"error": "no such track"}, 404)
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes="):
                a, _, b = rng[6:].partition("-")
                start = int(a) if a else max(0, len(data) - int(b))
                end = int(b) if (a and b) else len(data) - 1
                end = min(end, len(data) - 1)
                if start >= len(data):
                    return self._send(416, b"", "audio/wav", {"Content-Range": f"bytes */{len(data)}"})
                return self._send(206, data[start:end + 1], "audio/wav",
                                  {"Accept-Ranges": "bytes", "Content-Range": f"bytes {start}-{end}/{len(data)}"})
            return self._send(200, data, "audio/wav", {"Accept-Ranges": "bytes"})

        def _static(self, path: str):
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (WEB_ROOT / rel).resolve()
            if WEB_ROOT not in target.parents or not target.is_file() or target.suffix == ".py":
                return self._json({"error": "not found"}, 404)
            self._send(200, target.read_bytes(), CONTENT_TYPES.get(target.suffix, "application/octet-stream"))

    return Handler


def serve(port: int = 8765, host: str = "127.0.0.1", data_dir: Path | None = None,
          events_url: str | None = None) -> ThreadingHTTPServer:
    data_dir = Path(data_dir or os.environ.get("REMIXER_DATA_DIR") or REPO_ROOT / "data")
    backend = MockBackend(data_dir, events_url)
    httpd = ThreadingHTTPServer((host, port), make_handler(backend))
    httpd.backend = backend
    return httpd


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--events-url", default=None, help="where the player posts events (default /api/events)")
    a = ap.parse_args(argv)
    httpd = serve(a.port, a.host, a.data_dir, a.events_url)
    print(f"mock backend on http://{a.host}:{httpd.server_address[1]}/ (events: {a.events_url or '/api/events'})")
    httpd.serve_forever()


if __name__ == "__main__":
    main()

"""T-028 / T-029: the Ollama LLMClient against a scripted Ollama HTTP server, and the nightly job.

The fake server speaks Ollama's /api/tags and /api/generate. Its replies come from the insight layer's
``heuristic_script`` (or ``garbage_script``), so the real client round-trips analyst, skeptic and narrator
requests over HTTP exactly as it would against a local model.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from remixer.adapters.insight_job import CatalogTrackFeatures, due, load_state, run_job
from remixer.adapters.ollama_llm import OllamaClient
from remixer.insights.llm import MockLLM, canonical, read_request
from remixer.insights.mock import garbage_script, heuristic_script
from remixer.insights.pipeline import InsightConfig, InsightState, run_nightly
from remixer.insights.scenarios import confound_world

MODEL = "llama3.2:3b"


class FakeOllama:
    def __init__(self, script=heuristic_script, models=(MODEL,)):
        self.script, self.models, self.calls = script, list(models), []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, obj):
                data = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._send({"models": [{"name": m} for m in outer.models]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.calls.append(body)
                reply = outer.script(read_request(body["prompt"]), body.get("system"))
                self._send({"model": body["model"], "response": reply if isinstance(reply, str) else canonical(reply),
                            "done": True})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def ollama():
    srv = FakeOllama()
    yield srv
    srv.close()


@pytest.fixture(scope="module")
def world():
    return confound_world(seed=0, days=10, n_dislike=6, n_per_confound=2)


def dead_url() -> str:
    srv = FakeOllama()
    url = srv.url
    srv.close()
    return url


def test_available_reflects_server_and_model(ollama):
    assert OllamaClient(ollama.url, MODEL).available()
    assert not OllamaClient(ollama.url, "not-pulled:7b").available()
    assert not OllamaClient(dead_url(), MODEL).available()


def test_complete_sends_json_format_and_options(ollama):
    c = OllamaClient(ollama.url, MODEL)
    out = c.complete('do it\n\nREQUEST:\n{"role": "narrator", "items": []}', system="sys", temperature=0,
                     response_format="json")
    assert json.loads(out) == {"items": []}
    body = ollama.calls[-1]
    assert body["format"] == "json" and body["options"] == {"temperature": 0} and body["system"] == "sys"
    assert body["stream"] is False and body["model"] == MODEL and body["think"] is False


def test_thinking_only_reply_is_used():
    """A thinking model that ignores think=false still answers: the client falls back to "thinking"."""
    srv = FakeOllama(script=lambda req, system: "")
    srv.server.RequestHandlerClass.do_POST = _thinking_post(srv)
    try:
        assert json.loads(OllamaClient(srv.url, MODEL).complete('x\nREQUEST:\n{"items": []}')) == {"items": []}
    finally:
        srv.close()


def _thinking_post(srv):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        srv.calls.append(body)
        self._send({"model": body["model"], "response": "", "thinking": '{"items": []}', "done": True})
    return do_POST


def test_roles_round_trip_like_the_mock(ollama, world):
    """Same nights through HTTP and through MockLLM give the same state (cache keys use the model id)."""
    cfg = InsightConfig(utc_offset_minutes=world.utc_offset_minutes)
    via_http, via_mock = InsightState(), InsightState()
    client, mock = OllamaClient(ollama.url, MODEL), MockLLM(heuristic_script, model=MODEL)
    for now in world.night_ends():
        via_http, rep = run_nightly(world.events, via_http, client, now, world.features, cfg)
        via_mock, _ = run_nightly(world.events, via_mock, mock, now, world.features, cfg)
        assert not rep.errors
    assert via_http.to_json() == via_mock.to_json()
    assert {read_request(c["prompt"])["role"] for c in ollama.calls} == {"analyst", "skeptic", "narrator"}
    assert any(r.state in ("shown", "proposed") for r in via_http.records.values())


def test_malformed_replies_fall_back(world):
    srv = FakeOllama(script=garbage_script)
    try:
        cfg = InsightConfig(utc_offset_minutes=world.utc_offset_minutes)
        state, invalid, calls = InsightState(), 0, 0
        for now in world.night_ends()[:4]:
            state, rep = run_nightly(world.events, state, OllamaClient(srv.url, MODEL), now, world.features, cfg)
            invalid += rep.llm.get("invalid", 0)
            calls += rep.llm.get("calls", 0)
        assert calls == len(srv.calls) > 0 and invalid == calls   # every garbage reply rejected, none crashed
        assert all(r.channel == "inbox" for r in state.records.values())
    finally:
        srv.close()


@pytest.fixture
def tenant(open_tenant, world):
    a = open_tenant("tenant-a")
    a.events.append("playback", [e.to_row() for e in world.events])
    return a


def test_job_night_equals_direct_run_and_rerun_is_free(tenant, ollama, world):
    cfg = InsightConfig(utc_offset_minutes=world.utc_offset_minutes)
    client = OllamaClient(ollama.url, MODEL)
    direct = InsightState()
    for now in world.night_ends()[:5]:
        rep = run_job(tenant, now, client, world.features, cfg)
        assert "skipped" not in rep
        direct, _ = run_nightly(world.events, direct, MockLLM(heuristic_script, model=MODEL), now, world.features, cfg)
        assert load_state(tenant).to_json() == direct.to_json()
    n = len(ollama.calls)
    again = run_job(tenant, world.night_ends()[4], client, world.features, cfg)
    assert len(ollama.calls) == n and again["llm"]["calls"] == 0
    assert not due(tenant, world.night_ends()[4], world.utc_offset_minutes)


def test_down_model_skips_without_losing_state(tenant, ollama, world):
    cfg = InsightConfig(utc_offset_minutes=world.utc_offset_minutes)
    nights = world.night_ends()
    run_job(tenant, nights[2], OllamaClient(ollama.url, MODEL), world.features, cfg)
    before = load_state(tenant).to_json()
    rep = run_job(tenant, nights[3], OllamaClient(dead_url(), MODEL), world.features, cfg)
    assert rep["skipped"] == "llm unavailable"
    assert load_state(tenant).to_json() == before
    assert due(tenant, nights[3], world.utc_offset_minutes)


def test_recipe_tracks_get_window_features(tmp_path):
    from remixer.adapters.planner_catalog import SqliteRecipeStore
    from remixer.adapters.sqlite_catalog import SqliteCatalog
    from remixer.planner.model import Placement, Recipe, Section

    cat = SqliteCatalog(tmp_path / "c.sqlite")
    try:
        store = SqliteRecipeStore(cat)
        secs = (Section(0, 0, 8000, 120.0, "A minor", 4, 0.5, 1,
                        (Placement("s:drums", "s", "drums", 0, 8000, 0, 8000),)),
                Section(1, 8000, 16000, 124.0, "A minor", 4, 0.7, 2,
                        (Placement("s:drums", "s", "drums", 0, 8000, 8000, 16000),
                         Placement("t:vocals", "t", "vocals", 0, 6000, 10000, 16000))))
        r = Recipe(secs, 1, "b", 2)
        store.put(r)
        f = CatalogTrackFeatures(cat, store).window_features(r.root_id, r.recipe_id)
        assert [w.index for w in f] == [0, 1, 2, 3]
        assert f[0].section == "section 0" and f[0].tempo_bpm == 120.0 and f[0].stems == {"drums"}
        assert f[2].section == "section 1" and f[2].stems == {"drums", "vocals"}
        assert CatalogTrackFeatures(cat, store).window_features("unknown", "unknown") is None
    finally:
        cat.close()

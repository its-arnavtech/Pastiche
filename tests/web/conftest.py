"""Headless player tests: a mock backend per test and one Chromium per session."""
import importlib.util
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

_SPEC = importlib.util.spec_from_file_location(
    "mock_server", Path(__file__).resolve().parents[2] / "web" / "mock_server.py")
mock_server = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mock_server)


def pytest_collection_modifyitems(items):
    for item in items:
        if "tests/web/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.web)


def start_server(data_dir: Path):
    httpd = mock_server.serve(port=0, data_dir=data_dir)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    host, port = httpd.server_address
    return SimpleNamespace(url=f"http://{host}:{port}", backend=httpd.backend, httpd=httpd)


def start_fastapi(data_dir: Path):
    """The real backend (remixer.server.app) on real adapters, seeded with the mock's demo content."""
    import copy
    import socket
    import time

    uvicorn = pytest.importorskip("uvicorn")
    from remixer.adapters import build
    from remixer.config import DEFAULT_PROFILE, Profile, compute_resources
    from remixer.server.app import PlayerBackend, create_app, seed_demo

    data_dir.mkdir(parents=True, exist_ok=True)
    adapters = build(Profile(raw=copy.deepcopy(DEFAULT_PROFILE), resources=compute_resources({}), data_dir=data_dir))
    seed_demo(adapters)
    backend = PlayerBackend(adapters)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    srv = uvicorn.Server(uvicorn.Config(create_app(backend), log_level="warning"))
    t = threading.Thread(target=srv.run, kwargs={"sockets": [sock]}, daemon=True)
    t.start()
    while not srv.started:
        time.sleep(0.02)

    def shutdown():
        srv.should_exit = True
        t.join(timeout=10)
        adapters.catalog.close()

    host, port = sock.getsockname()
    return SimpleNamespace(url=f"http://{host}:{port}", backend=backend, httpd=SimpleNamespace(shutdown=shutdown))


STARTERS = {"mock": start_server, "fastapi": start_fastapi}


@pytest.fixture(params=sorted(STARTERS))
def backend_kind(request):
    return request.param


@pytest.fixture
def server(tmp_path, backend_kind):
    s = STARTERS[backend_kind](tmp_path / "a")
    yield s
    s.httpd.shutdown()


@pytest.fixture
def other_server(tmp_path, backend_kind):
    s = STARTERS[backend_kind](tmp_path / "b")
    yield s
    s.httpd.shutdown()


@pytest.fixture(scope="session")
def browser():
    with sync_api.sync_playwright() as p:
        args = ["--autoplay-policy=no-user-gesture-required"]
        try:
            b = p.chromium.launch(args=args)
        except Exception as e:  # bundled build missing: fall back to the system Edge (Chromium) on Windows
            try:
                b = p.chromium.launch(channel="msedge", args=args)
            except Exception:
                pytest.skip(f"chromium not available ({e}); run `uv run playwright install chromium`")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.dialogs, pg.errors = [], []
    pg.on("dialog", lambda d: (pg.dialogs.append(d.message), d.dismiss()))
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and not (m.location or {}).get("url", "").endswith("/favicon.ico")
          and pg.errors.append(m.text))  # full Edge (fallback browser) requests /favicon.ico on its own
    yield pg
    assert pg.dialogs == [], "the UI must never prompt"
    assert pg.errors == []
    ctx.close()

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


@pytest.fixture
def server(tmp_path):
    s = start_server(tmp_path / "a")
    yield s
    s.httpd.shutdown()


@pytest.fixture
def other_server(tmp_path):
    s = start_server(tmp_path / "b")
    yield s
    s.httpd.shutdown()


@pytest.fixture(scope="session")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        except Exception as e:  # browser binary missing
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
    pg.on("console", lambda m: m.type == "error" and pg.errors.append(m.text))
    yield pg
    assert pg.dialogs == [], "the UI must never prompt"
    assert pg.errors == []
    ctx.close()

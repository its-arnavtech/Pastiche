"""Headless player: every control emits one T-014 event, seeks are exactly 5 s, no prompts."""
import remixer
from remixer.analytics.events import Event, validate_event
from remixer.analytics.interpret import interpret

import pytest


def open_player(page, base, query=""):
    page.goto(f"{base}/{query}")
    page.wait_for_selector("body[data-ready=true]")
    page.wait_for_function("window.__player.audio.readyState >= 1")


def flush(page):
    page.wait_for_function("window.__player.emitter.pending() === 0")
    page.evaluate("window.__player.emitter.flush()")


def session_events(page, server):
    flush(page)
    sid = page.evaluate("sessionStorage.getItem('remixer.session_id')")
    evs = [e for e in server.backend.events() if e["session_id"] == sid]
    return sorted(evs, key=lambda e: e["client_info"]["seq"])


def current_time(page) -> float:
    return page.evaluate("window.__player.audio.currentTime")


def set_time(page, seconds: float):
    page.evaluate(f"""() => new Promise((res) => {{
        const a = window.__player.audio;
        a.addEventListener('seeked', () => res(), {{ once: true }});
        a.currentTime = {seconds};
    }})""")


def types(evs):
    return [e["event_type"] for e in evs]


def test_shows_project_name_and_endpoint(page, server):
    open_player(page, server.url)
    assert page.text_content("[data-project-name]") == remixer.PROJECT_NAME
    assert remixer.PROJECT_NAME in page.title()
    assert page.text_content("#endpoint") == "/api/events"
    assert page.text_content("#title") == "Aurora"
    assert page.locator("#playlist li").count() == 4


def test_play_pause_emit_events_with_positions(page, server):
    open_player(page, server.url)
    page.click("#play")
    page.wait_for_function("window.__player.audio.currentTime > 0.6")
    page.click("#play")
    evs = session_events(page, server)
    assert types(evs) == ["play", "pause"]
    assert evs[0]["position_ms"] == 0
    assert evs[1]["position_ms"] >= 600
    assert page.get_attribute("#play", "data-state") == "paused"
    for e in evs:
        assert validate_event(e) == []
        assert e["track_id"] == "src-aurora" and e["track_version"] == "v1"
        assert e["source_kind"] == "source"
        assert e["client_info"]["duration_ms"] == 45_000


def test_seek_buttons_move_exactly_five_seconds(page, server):
    open_player(page, server.url)
    set_time(page, 12.0)
    page.click("#fwd")
    page.wait_for_function("Math.abs(window.__player.audio.currentTime - 17) < 0.01")
    page.click("#back")
    page.click("#back")
    page.wait_for_function("Math.abs(window.__player.audio.currentTime - 7) < 0.01")
    evs = session_events(page, server)
    assert types(evs) == ["seek_fwd_5s", "seek_back_5s", "seek_back_5s"]
    assert [e["position_ms"] for e in evs] == [12_000, 17_000, 12_000]


def test_seek_back_clamps_at_zero(page, server):
    open_player(page, server.url)
    set_time(page, 2.0)
    page.click("#back")
    page.wait_for_function("window.__player.audio.currentTime === 0")
    assert [e["position_ms"] for e in session_events(page, server)] == [2_000]


def test_next_and_previous(page, server):
    open_player(page, server.url)
    page.click("#next")
    page.wait_for_function("window.__player.state.index === 1")
    assert page.text_content("#title") == "Recombined #1"
    assert page.text_content("#kind") == "Generated"
    page.wait_for_function("window.__player.audio.readyState >= 1")
    set_time(page, 10.0)
    page.click("#prev")  # past 3 s: restart the same track
    page.wait_for_function("window.__player.audio.currentTime < 1")
    assert page.evaluate("window.__player.state.index") == 1
    page.click("#play")  # pause so the playhead stays under 3 s
    set_time(page, 1.0)
    page.click("#prev")  # under 3 s: back to the previous track
    page.wait_for_function("window.__player.state.index === 0")
    evs = session_events(page, server)
    assert types(evs) == ["next", "play", "previous", "play", "pause", "previous", "play"]
    assert evs[0]["track_id"] == "src-aurora"
    assert evs[1]["track_id"] == evs[2]["track_id"] == "gen-0001"
    assert evs[1]["track_version"] == "r3f9c" and evs[1]["source_kind"] == "generated"
    assert evs[2]["position_ms"] >= 10_000
    assert evs[5]["track_id"] == "gen-0001" and evs[5]["position_ms"] < 3_000
    assert evs[6]["track_id"] == "src-aurora" and evs[6]["position_ms"] == 0


def test_track_end_auto_advances(page, server):
    open_player(page, server.url)
    page.click("#play")
    for _ in range(9):
        page.click("#fwd")
    page.wait_for_function("window.__player.state.index === 1", timeout=10_000)
    evs = session_events(page, server)
    assert types(evs) == ["play", *["seek_fwd_5s"] * 9, "track_end", "play"]
    end = evs[-2]
    assert end["track_id"] == "src-aurora" and end["position_ms"] == 45_000
    assert evs[-1]["track_id"] == "gen-0001" and evs[-1]["position_ms"] == 0


def test_keyboard_shortcuts_emit_the_same_events(page, server):
    open_player(page, server.url)
    page.keyboard.press("Space")
    page.wait_for_function("!window.__player.audio.paused")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("Space")
    page.keyboard.press("Shift+ArrowRight")
    page.wait_for_function("window.__player.state.index === 1")
    page.keyboard.press("Shift+ArrowLeft")
    page.wait_for_function("window.__player.state.index === 0")
    assert types(session_events(page, server)) == [
        "play", "seek_fwd_5s", "seek_back_5s", "pause", "next", "play", "previous", "play"]


def test_ratings_toggle_and_persist(page, server):
    open_player(page, server.url)
    page.click("#rate-up")
    assert page.get_attribute("#rate-up", "aria-pressed") == "true"
    page.click("#rate-up")
    assert page.get_attribute("#rate-up", "aria-pressed") == "false"
    page.click("#rate-down")
    page.click("#rate-tired")
    page.click("#rate-tired")  # already resting: no second event
    assert page.get_attribute("#rate-down", "aria-pressed") == "true"
    assert page.get_attribute("#rate-tired", "aria-pressed") == "true"
    evs = session_events(page, server)
    assert types(evs) == ["rate_up", "rate_clear", "rate_down", "rate_tired"]
    assert all(e["track_id"] == "src-aurora" for e in evs)

    assert server.backend.ratings()["src-aurora"]["rating"] == "down"
    page.reload()
    page.wait_for_selector("body[data-ready=true]")
    assert page.get_attribute("#rate-down", "aria-pressed") == "true"
    assert page.get_attribute("#rate-tired", "aria-pressed") == "true"
    assert "Disliked" in page.text_content("#playlist li:first-child .badges")
    page.click("#next")
    page.wait_for_function("window.__player.state.index === 1")
    assert page.get_attribute("#rate-down", "aria-pressed") == "false"


def test_ui_session_reconstructs_as_burst_with_undo(page, server):
    open_player(page, server.url)
    page.click("#play")
    page.wait_for_function("window.__player.audio.currentTime > 0.3")
    for _ in range(3):
        page.click("#fwd")
    page.click("#back")
    page.wait_for_timeout(300)
    page.click("#next")
    page.wait_for_function("window.__player.state.index === 1")
    raw = session_events(page, server)
    assert all(validate_event(e) == [] for e in raw)
    result = interpret([Event.from_dict(e) for e in raw])
    first = next(lst for lst in result.listens if lst.track_id == "src-aurora")
    assert [(b.n_presses, b.undone) for b in first.bursts] == [(3, 1)]
    assert first.end_reason == "next"
    assert any(s.kind == "undo" for s in result.signals)


def test_events_go_to_configured_url(page, server, other_server):
    url = f"{other_server.url}/api/events"
    open_player(page, server.url, f"?events={url}")
    assert page.text_content("#endpoint") == url
    page.click("#play")
    page.click("#fwd")
    page.click("#play")
    page.wait_for_function("window.__player.emitter.pending() === 0")
    page.evaluate("window.__player.emitter.flush()")
    assert types(other_server.backend.events()) == ["play", "seek_fwd_5s", "pause"]
    assert server.backend.events() == []
    inbox_href = page.eval_on_selector("nav a:last-child", "a => a.href")
    assert "/inbox.html?events=" in inbox_href


def test_rejected_event_is_dropped_not_retried(page, server):
    open_player(page, server.url)
    page.evaluate("""window.__player.emitter.emit({
        track: window.__player.state.tracks[0], event_type: 'not_a_type', position_ms: 0 })""")
    page.wait_for_function("window.__player.emitter.stats.rejected === 1")
    page.errors.clear()  # the console error for the rejected event is expected here
    assert server.backend.events() == []


@pytest.mark.parametrize("path", ["/mock_server.py", "/../pyproject.toml", "/nope.html"])
def test_static_server_refuses_outside_files(page, server, path):
    resp = page.request.get(server.url + path)
    assert resp.status == 404

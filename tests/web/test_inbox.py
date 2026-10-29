"""Passive insights inbox: three answers, only "yes" confirms, nothing ever pops up."""
import re

from remixer.analytics.events import validate_event

SENTENCE = re.compile(r"^You've skipped \d+:\d\d-\d+:\d\d in (\d+) of (\d+) listens\.$")


def open_inbox(page, base, query=""):
    page.goto(f"{base}/inbox.html{query}")
    page.wait_for_selector("body[data-ready=true]")


def flush(page):
    page.wait_for_function("window.__inbox.emitter.pending() === 0")
    page.evaluate("window.__inbox.emitter.flush()")


def by_id(server):
    return {i["insight_id"]: i for i in server.backend.insights()}


def test_seeded_insights_come_from_the_insight_pipeline(server):
    items = server.backend.insights()
    got = {(i["track_id"], i["start_ms"], i["end_ms"]) for i in items}
    assert got == {("gen-0001", 10_000, 15_000), ("gen-0002", 30_000, 40_000), ("src-aurora", 20_000, 30_000)}
    for i in items:
        assert i["answer"] is None and i["confirmed"] is False and i["state"] == "shown" and i["pending"]
        m = SENTENCE.match(i["hypothesis"])
        assert m and int(m.group(1)) <= int(m.group(2)) and int(m.group(2)) >= 3
        assert "harsh synths enter" in i["why"]
    assert len({i["shown_day"] for i in items}) == 3, "at most one new insight per day"


def test_inbox_lists_pending_insights_and_badge(page, server):
    open_inbox(page, server.url)
    assert page.locator(".insight").count() == 3
    assert page.is_hidden("#empty")
    assert page.text_content("[data-insight-count]") == "3"
    for card in page.locator(".insight").all():
        labels = card.locator("button").all_text_contents()
        assert labels == ["Yes, skip it from now on", "No, I like it", "Not sure yet"]


def test_answers_emit_events_and_only_yes_confirms(page, server):
    open_inbox(page, server.url)
    ids = page.eval_on_selector_all(".insight", "els => els.map(e => e.dataset.insightId)")
    for insight_id, answer in zip(ids, ["yes", "no", "unsure"]):
        page.click(f"[data-insight-id='{insight_id}'] button[data-answer={answer}]")
    flush(page)

    evs = server.backend.events()
    assert [e["event_type"] for e in evs] == ["insight_yes", "insight_no", "insight_unsure"]
    assert [e["payload"]["insight_id"] for e in evs] == ids
    assert all(validate_event(e) == [] for e in evs)
    state = by_id(server)
    for e in evs:
        assert e["position_ms"] == state[e["payload"]["insight_id"]]["start_ms"]
        assert e["track_id"] == state[e["payload"]["insight_id"]]["track_id"]
    assert [state[i]["answer"] for i in ids] == ["yes", "no", "unsure"]
    assert [state[i]["confirmed"] for i in ids] == [True, False, False]
    assert [state[i]["state"] for i in ids] == ["confirmed", "dismissed", "not_sure"]
    assert state[ids[2]]["ask_again_on"] and not state[ids[2]]["pending"]

    page.wait_for_function("document.querySelector('[data-insight-count]').hidden === true")
    page.reload()
    page.wait_for_selector("body[data-ready=true]")
    pressed = page.eval_on_selector_all(
        ".insight", "els => els.map(e => [e.dataset.insightId, e.querySelector('[aria-pressed=true]')?.dataset.answer])")
    assert dict(pressed) == dict(zip(ids, ["yes", "no", "unsure"]))
    unsure = page.text_content(f"[data-insight-id='{ids[2]}'] .status")
    assert unsure.startswith("Not sure yet: we'll ask again on ")


def test_not_sure_comes_back_after_the_delay(server):
    insight_id = server.backend.insights()[0]["insight_id"]
    item = next(i for i in server.backend.insights() if i["insight_id"] == insight_id)
    server.backend.append([{
        "event_id": "u1", "session_id": "inbox", "track_id": item["track_id"],
        "track_version": item["track_version"], "event_type": "insight_unsure", "position_ms": item["start_ms"],
        "wall_time": "2026-10-01T12:00:00Z", "source_kind": item["source_kind"],
        "payload": {"insight_id": insight_id}}])
    later = {i["insight_id"]: i for i in server.backend.insights(now_ms=1_790_000_000_000 + 30 * 86_400_000)}
    now = {i["insight_id"]: i for i in server.backend.insights(now_ms=1_790_000_000_000)}
    assert now[insight_id]["state"] == "not_sure" and now[insight_id]["ask_again_on"] == "2026-10-08"
    assert later[insight_id]["state"] == "shown" and later[insight_id]["pending"]


def test_changing_an_answer_unconfirms(page, server):
    open_inbox(page, server.url)
    first = page.locator(".insight").first
    insight_id = first.get_attribute("data-insight-id")
    first.locator("button[data-answer=yes]").click()
    first.locator("button[data-answer=no]").click()
    flush(page)
    assert by_id(server)[insight_id]["confirmed"] is False
    assert by_id(server)[insight_id]["answer"] == "no"


def test_player_badge_counts_pending(page, server):
    page.goto(server.url)
    page.wait_for_selector("body[data-ready=true]")
    page.wait_for_function("document.querySelector('[data-insight-count]').textContent === '3'")


def test_inbox_events_follow_configured_url(page, server, other_server):
    url = f"{other_server.url}/api/events"
    open_inbox(page, server.url, f"?events={url}")
    page.locator(".insight button[data-answer=unsure]").first.click()
    flush(page)
    assert [e["event_type"] for e in other_server.backend.events()] == ["insight_unsure"]
    assert server.backend.events() == []

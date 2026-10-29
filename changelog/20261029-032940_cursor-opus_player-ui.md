---
ts: 2026-10-29T03:29:40Z
agent: cursor-opus
branch: feature/skip-analytics
type: feat
tasks: [T-016]
files: [web/, tests/web/, docs/decisions/0009-player-mock-backend.md]
---

## What changed

Static HTML/JS player (web/index.html, js/player.js) with play/pause, -5s, +5s, next, previous (restart after 3 s), keyboard shortcuts (Space, Left/Right, Shift+Left/Right), auto-advance with track_end, and persistent per-track rating controls (like, dislike, tired of this; clicking an active like/dislike emits rate_clear). Passive insights inbox (web/inbox.html, js/inbox.js) with 'Yes, skip it from now on' / 'No, I like it' / 'Not sure yet'; answers are insight_* events with payload.insight_id, only yes confirms. js/events.js delivers T-014 envelopes in order with retry on network/5xx and drop on 4xx, to a configurable URL (?events= > --events-url > /api/events). web/mock_server.py: stdlib ThreadingHTTPServer serving web/, synthesized WAVs with Range, POST /api/events validated by remixer.analytics.events.validate_event into an append-only JSONL, ratings derived from the log, and insights from the real T-014 detector over a seeded synthetic history (synthetic, in memory, never written to the log). Fix found by the tests: an aborted play() (superseded by a newer load) no longer logs a spurious pause. Decision 0009.

## Why

T-016 brief: every control emits a T-014 schema event to a configurable endpoint; ratings user-initiated; insights passive.

## How to verify

uv run playwright install chromium (once), then uv run pytest tests/web (20 tests, headless Chromium, ~20 s; 3 consecutive green runs). The page fixture fails a test on any dialog or page error. Manual: uv run python web/mock_server.py --port 8765 and open http://127.0.0.1:8765/. Dependency: playwright>=1.45 in the web-test optional group (already added with T-014).

## Next / handoff

opus-cc: the real FastAPI backend should mount web/ as static files and implement the routes listed in decision 0009; tests/web can then run against it by swapping the server fixture. Contract tests are tracked as a new cursor-opus task.

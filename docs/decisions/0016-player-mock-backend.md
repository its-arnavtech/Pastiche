# 0016: Player mock backend and inbox semantics

- Date: 2026-10-29
- Agent: cursor-opus
- Tasks: T-016

## Decision

1. The mock backend (`web/mock_server.py`) is the standard library's `ThreadingHTTPServer`, not FastAPI.
   The task file says FastAPI, but the brief asks for minimal dependencies that run on a plain CI machine,
   and the backend is a test double. The real FastAPI backend can serve the same static `web/` files
   and implement the same six routes (`/api/config`, `/api/tracks`, `/api/events` GET/POST,
   `/api/ratings`, `/api/insights`, `/audio/<id>.wav` with Range).
2. The events URL is configurable in three places, highest priority first: the `?events=` query
   parameter, the backend's `--events-url`, then the `/api/events` default. The endpoint must accept
   a JSON list of events and allow CORS.
3. "Not sure yet" keeps an insight pending: it counts in the inbox badge and stays unconfirmed.
   Only "Yes, skip it from now on" sets `confirmed=true`; a later "No" un-confirms it.
4. The player emits events and never prompts. There are no dialogs, toasts asking for input or auto-rating.
   The Playwright `page` fixture fails any test that sees a dialog or a page error.
5. Previous restarts the track after 3 s (same threshold as `InterpretConfig`). Track end emits
   `track_end` at `duration_ms` and auto-advances with a `play` at 0. An aborted `play()` promise
   (superseded by a newer load) emits nothing.
6. "Tired of this" is shown as active for 3 days and is not re-emitted while active. Like and
   dislike toggle; clicking the active one emits `rate_clear`.

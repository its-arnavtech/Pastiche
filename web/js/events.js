// Event envelope and in-order delivery to the events endpoint (T-014 schema).
// Network or 5xx failures are retried with backoff; 4xx (schema rejection) is dropped and logged.

const uuid = () =>
  (globalThis.crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
      });

export function sessionId() {
  let id = sessionStorage.getItem("remixer.session_id");
  if (!id) {
    id = uuid();
    sessionStorage.setItem("remixer.session_id", id);
  }
  return id;
}

export function createEmitter(url, { player = "web-mock/1" } = {}) {
  const session = sessionId();
  const queue = [];
  const stats = { emitted: 0, sent: 0, rejected: 0, retries: 0 };
  const listeners = [];
  let seq = 0;
  let pumping = null;

  async function pump() {
    let backoff = 250;
    while (queue.length) {
      const batch = queue.slice(0, 50);
      try {
        const r = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(batch),
          keepalive: true,
        });
        if (r.status >= 400 && r.status < 500) {
          console.error("events rejected", await r.text());
          stats.rejected += batch.length;
        } else if (!r.ok) {
          throw new Error(`HTTP ${r.status}`);
        } else {
          stats.sent += batch.length;
        }
        queue.splice(0, batch.length);
        backoff = 250;
      } catch (err) {
        stats.retries += 1;
        await new Promise((res) => setTimeout(res, backoff));
        backoff = Math.min(backoff * 2, 5000);
      }
      listeners.forEach((fn) => fn(stats));
    }
    pumping = null;
  }

  function emit({ track, event_type, position_ms, payload = {}, extraInfo = {} }) {
    const ev = {
      event_id: uuid(),
      session_id: session,
      track_id: track.track_id,
      track_version: track.track_version,
      event_type,
      position_ms: Math.max(0, Math.round(position_ms)),
      wall_time: Date.now(),
      source_kind: track.source_kind,
      client_info: {
        player,
        seq: seq++,
        duration_ms: track.duration_ms,
        user_agent: navigator.userAgent,
        ...extraInfo,
      },
      payload,
    };
    queue.push(ev);
    stats.emitted += 1;
    listeners.forEach((fn) => fn(stats));
    if (!pumping) pumping = pump();
    return ev;
  }

  return {
    emit,
    stats,
    onChange: (fn) => listeners.push(fn),
    flush: () => pumping || Promise.resolve(),
    pending: () => queue.length,
  };
}

export async function loadConfig() {
  const cfg = await (await fetch("/api/config")).json();
  const override = new URLSearchParams(location.search).get("events");
  if (override) cfg.events_url = override;
  document.querySelectorAll("[data-project-name]").forEach((el) => (el.textContent = cfg.project_name));
  document.title = `${cfg.project_name} · ${document.title}`;
  return cfg;
}

export async function insightBadge() {
  const items = await (await fetch("/api/insights")).json();
  const pending = items.filter((i) => i.answer === null || i.answer === "unsure").length;
  document.querySelectorAll("[data-insight-count]").forEach((el) => {
    el.textContent = pending ? String(pending) : "";
    el.hidden = pending === 0;
  });
  return items;
}

export const fmt = (ms) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

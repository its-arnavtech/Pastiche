// Player: fixed 5-second seeks only, every control emits one event before it acts.
// Ratings are user-initiated: nothing here ever asks the user to rate.
import { createEmitter, fmt, insightBadge, loadConfig } from "./events.js";

const RESTART_THRESHOLD_MS = 3000; // previous after 3 s restarts the track (matches InterpretConfig)

const $ = (sel) => document.querySelector(sel);
const audio = $("#audio");
const state = { tracks: [], index: 0, ratings: {}, emitter: null, seekS: 5 };

const track = () => state.tracks[state.index];
const posMs = () => (audio.currentTime || 0) * 1000;

function emit(event_type, { position_ms = posMs(), payload } = {}) {
  return state.emitter.emit({ track: track(), event_type, position_ms, payload });
}

async function startPlayback() {
  emit("play");
  try {
    await audio.play();
  } catch (err) {
    // AbortError: a newer load()/play() superseded this one and logs its own events.
    if (err && err.name === "AbortError") return;
    emit("pause");
    console.warn("playback blocked", err);
  }
}

function load(index) {
  state.index = (index + state.tracks.length) % state.tracks.length;
  audio.src = track().audio_url;
  audio.currentTime = 0;
  render();
}

const controls = {
  togglePlay() {
    if (audio.paused) startPlayback();
    else {
      emit("pause");
      audio.pause();
    }
  },
  seekBack() {
    emit("seek_back_5s");
    audio.currentTime = Math.max(0, audio.currentTime - state.seekS);
  },
  seekFwd() {
    emit("seek_fwd_5s");
    const d = audio.duration || track().duration_ms / 1000;
    audio.currentTime = Math.min(d, audio.currentTime + state.seekS);
  },
  next() {
    emit("next");
    load(state.index + 1);
    startPlayback();
  },
  previous() {
    emit("previous");
    if (posMs() > RESTART_THRESHOLD_MS || state.index === 0) {
      audio.currentTime = 0;
    } else {
      load(state.index - 1);
    }
    startPlayback();
  },
};

audio.addEventListener("ended", () => {
  emit("track_end", { position_ms: track().duration_ms });
  load(state.index + 1);
  startPlayback();
});

// ------------------------------------------------------------------ ratings

function rate(kind) {
  const t = track();
  const st = (state.ratings[t.track_id] ||= { rating: null, tired_at: null });
  if (kind === "tired") {
    if (isTired(st)) return; // already marked; it fades on its own
    emit("rate_tired");
    st.tired_at = Date.now();
  } else if (st.rating === kind) {
    emit("rate_clear");
    st.rating = null;
  } else {
    emit(kind === "up" ? "rate_up" : "rate_down");
    st.rating = kind;
  }
  render();
}

const isTired = (st) => st && st.tired_at && Date.now() - st.tired_at < 3 * 86_400_000;

// ------------------------------------------------------------------ rendering

function render() {
  const t = track();
  if (!t) return;
  $("#title").textContent = t.title;
  $("#artist").textContent = t.artist;
  $("#kind").textContent = t.source_kind === "generated" ? "Generated" : "Source";
  $("#kind").dataset.kind = t.source_kind;
  $("#version").textContent = t.track_version;
  const st = state.ratings[t.track_id] || {};
  $("#rate-up").setAttribute("aria-pressed", String(st.rating === "up"));
  $("#rate-down").setAttribute("aria-pressed", String(st.rating === "down"));
  $("#rate-tired").setAttribute("aria-pressed", String(Boolean(isTired(st))));
  $("#rate-tired").title = isTired(st) ? "Marked: fades on its own over a few days" : "Rest this for a while";
  $("#play").setAttribute("aria-label", audio.paused ? "Play" : "Pause");
  $("#play").dataset.state = audio.paused ? "paused" : "playing";
  const ticks = $("#ticks");
  const n = Math.ceil(t.duration_ms / 5000);
  if (ticks.childElementCount !== n - 1) {
    ticks.replaceChildren(...Array.from({ length: n - 1 }, (_, i) => {
      const el = document.createElement("span");
      el.style.left = `${((i + 1) * 5000 * 100) / t.duration_ms}%`;
      return el;
    }));
  }
  document.querySelectorAll("#playlist li").forEach((li, i) => {
    li.classList.toggle("current", i === state.index);
    const r = state.ratings[state.tracks[i].track_id] || {};
    li.querySelector(".badges").textContent =
      [r.rating === "up" ? "Liked" : r.rating === "down" ? "Disliked" : "", isTired(r) ? "Resting" : ""]
        .filter(Boolean).join(" · ");
  });
  tick();
}

function tick() {
  const t = track();
  if (!t) return;
  const d = audio.duration ? audio.duration * 1000 : t.duration_ms;
  $("#elapsed").textContent = fmt(posMs());
  $("#duration").textContent = fmt(d);
  $("#bar").style.width = `${Math.min(100, (posMs() * 100) / d)}%`;
}

function renderPlaylist() {
  $("#playlist").replaceChildren(...state.tracks.map((t) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="t"></span><span class="a"></span><span class="badges"></span><span class="d"></span>`;
    li.querySelector(".t").textContent = t.title;
    li.querySelector(".a").textContent = `${t.artist} · ${t.source_kind}`;
    li.querySelector(".d").textContent = fmt(t.duration_ms);
    return li;
  }));
}

// ------------------------------------------------------------------ wiring

async function main() {
  const cfg = await loadConfig();
  state.seekS = (cfg.seek_ms || 5000) / 1000;
  state.emitter = createEmitter(cfg.events_url);
  state.emitter.onChange((s) => {
    $("#event-status").textContent = `${s.sent} events logged${s.emitted > s.sent + s.rejected ? ", sending…" : ""}`;
  });
  $("#endpoint").textContent = cfg.events_url;
  document.querySelectorAll("a[data-keep-query]").forEach((a) => (a.href += location.search));
  [state.tracks, state.ratings] = await Promise.all([
    fetch("/api/tracks").then((r) => r.json()),
    fetch("/api/ratings").then((r) => r.json()),
  ]);
  renderPlaylist();
  load(0);
  insightBadge();

  $("#play").onclick = controls.togglePlay;
  $("#back").onclick = controls.seekBack;
  $("#fwd").onclick = controls.seekFwd;
  $("#next").onclick = controls.next;
  $("#prev").onclick = controls.previous;
  $("#rate-up").onclick = () => rate("up");
  $("#rate-down").onclick = () => rate("down");
  $("#rate-tired").onclick = () => rate("tired");
  audio.addEventListener("timeupdate", tick);
  audio.addEventListener("play", render);
  audio.addEventListener("pause", render);
  audio.addEventListener("loadedmetadata", tick);

  document.addEventListener("keydown", (e) => {
    if (e.target.closest("button, input, textarea") && e.key === " ") return;
    const map = { " ": "togglePlay", ArrowLeft: e.shiftKey ? "previous" : "seekBack", ArrowRight: e.shiftKey ? "next" : "seekFwd" };
    if (map[e.key]) {
      e.preventDefault();
      controls[map[e.key]]();
    }
  });

  window.__player = { state, audio, emitter: state.emitter, controls };
  document.body.dataset.ready = "true";
}

main();

// Passive insights inbox: nothing here interrupts playback or pops up; the user comes here.
// Answers are events; only "Yes, skip it from now on" confirms an insight.
import { createEmitter, fmt, insightBadge, loadConfig } from "./events.js";

const ANSWERS = [
  ["insight_yes", "Yes, skip it from now on", "yes"],
  ["insight_no", "No, I like it", "no"],
  ["insight_unsure", "Not sure yet", "unsure"],
];
const LABEL = { yes: "Skipping from now on", no: "Kept: you like it", unsure: "Not sure yet: we'll ask again later" };

function statusText(ins) {
  if (ins.answer === "unsure" && ins.ask_again_on) return `Not sure yet: we'll ask again on ${ins.ask_again_on}`;
  return ins.answer ? LABEL[ins.answer] : "";
}

let emitter;

function card(ins) {
  const li = document.createElement("li");
  li.className = "insight";
  li.dataset.insightId = ins.insight_id;
  li.innerHTML = `
    <div class="meta"><span class="t"></span><span class="range"></span></div>
    <p class="hypothesis"></p>
    <p class="why" hidden></p>
    <div class="answers" role="group" aria-label="Your answer"></div>
    <p class="status" aria-live="polite"></p>`;
  li.querySelector(".t").textContent = ins.title;
  li.querySelector(".range").textContent = `${fmt(ins.start_ms)}–${fmt(ins.end_ms)}`;
  li.querySelector(".hypothesis").textContent = ins.hypothesis;
  if (ins.why) {
    li.querySelector(".why").textContent = ins.why;
    li.querySelector(".why").hidden = false;
  }
  const answers = li.querySelector(".answers");
  for (const [type, label, value] of ANSWERS) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.dataset.answer = value;
    b.setAttribute("aria-pressed", String(ins.answer === value));
    b.onclick = () => answer(ins, type, value, li);
    answers.append(b);
  }
  li.querySelector(".status").textContent = statusText(ins);
  return li;
}

function answer(ins, type, value, li) {
  emitter.emit({
    track: { track_id: ins.track_id, track_version: ins.track_version, source_kind: ins.source_kind },
    event_type: type,
    position_ms: ins.start_ms,
    payload: { insight_id: ins.insight_id },
  });
  ins.answer = value;
  li.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.answer === value)));
  li.querySelector(".status").textContent = LABEL[value];
  li.classList.toggle("answered", value !== "unsure");
  emitter.flush().then(insightBadge);
}

async function main() {
  const cfg = await loadConfig();
  emitter = createEmitter(cfg.events_url, { player: "web-mock/1 inbox" });
  document.querySelectorAll("a[data-keep-query]").forEach((a) => (a.href += location.search));
  const items = await insightBadge();
  const list = document.querySelector("#insights");
  list.replaceChildren(...items.map(card));
  list.querySelectorAll(".insight").forEach((li, i) => li.classList.toggle("answered", ["yes", "no"].includes(items[i].answer)));
  document.querySelector("#empty").hidden = items.length > 0;
  window.__inbox = { emitter, items };
  document.body.dataset.ready = "true";
}

main();

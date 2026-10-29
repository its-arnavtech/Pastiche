"""Analyst, Skeptic and Narrator: pure functions around one batched LLM call each.

Each role sends the windows of one track in one request and validates the reply against its schema
plus semantic checks: a narrated sentence must quote the real range and counts, and a non-accepting
verdict must give a reason. Anything malformed falls back to a deterministic answer for that window.
Nothing here raises on bad model output. Only ``BudgetExhausted`` propagates, so the caller can defer.

The Skeptic is two layers. Deterministic confound rules (``rule_reasons``) run on the evidence
first, and hard failures never reach the model. The model's verdict is then combined with the
rules, and the stricter of the two wins. A model can downgrade or reject an insight but never
overrule a rule (decision 0021).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .cost import BudgetExhausted, Caller
from .evidence import WindowEvidence, fmt_ms
from .schema import LLMOutputError, parse_json_object, validate

PROMPT_VERSION = "insights-1"
CAUSES = ("stem_entry", "stem_exit", "loudness_jump", "tempo_change", "section_change", "track_start",
          "repetition", "unknown")
REASON_CODES = ("none", "intro", "shuffle", "time_of_day", "few_listens", "undo", "one_off_session", "other")
VERDICTS = ("accept", "downgrade", "reject")
_SEVERITY = {v: i for i, v in enumerate(VERDICTS)}
MAX_SENTENCE = 140


def _items_schema(item: dict) -> dict:
    return {"type": "object", "required": ["items"],
            "properties": {"items": {"type": "array", "maxItems": 64, "items": item}}}


ANALYST_SCHEMA = _items_schema({
    "type": "object", "required": ["window_id", "hypothesis", "cause", "confidence"],
    "properties": {"window_id": {"type": "string"},
                   "hypothesis": {"type": "string", "minLength": 1, "maxLength": 200},
                   "cause": {"enum": list(CAUSES)},
                   "confidence": {"type": "number", "minimum": 0, "maximum": 1}}})
SKEPTIC_SCHEMA = _items_schema({
    "type": "object", "required": ["window_id", "verdict", "confidence", "reasons"],
    "properties": {"window_id": {"type": "string"}, "verdict": {"enum": list(VERDICTS)},
                   "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                   "reasons": {"type": "array", "minItems": 1, "maxItems": 8, "items": {
                       "type": "object", "required": ["code", "detail"],
                       "properties": {"code": {"enum": list(REASON_CODES)},
                                      "detail": {"type": "string", "minLength": 1, "maxLength": 200}}}}}})
NARRATOR_SCHEMA = _items_schema({
    "type": "object", "required": ["window_id", "sentence"],
    "properties": {"window_id": {"type": "string"},
                   "sentence": {"type": "string", "minLength": 8, "maxLength": MAX_SENTENCE}}})

_JSON_ONLY = "Reply with one JSON object and nothing else."
ANALYST_SYSTEM = (
    "You are the Analyst for a personal music player. For each skipped time window, propose one short "
    "hypothesis for why the listener skips it, using only the evidence given: what changes in the music "
    "at that moment and the play history. Pick the cause from: " + ", ".join(CAUSES) + ". Give a "
    "confidence from 0 to 1. Do not invent numbers. " + _JSON_ONLY +
    ' Shape: {"items":[{"window_id":"...","hypothesis":"...","cause":"...","confidence":0.0}]}')
SKEPTIC_SYSTEM = (
    "You are the Skeptic. Try to reject or downgrade each hypothesis by checking confounds: an intro "
    "that is skipped from the very start, skips that only happen in shuffle sessions, skips that only "
    "happen at one time of day (mood), too few distinct listens or sessions, skips that were undone, "
    "and skips concentrated in one session. Verdict is accept, downgrade or reject. Always give at "
    "least one reason; use code none only when accepting. Reason codes: " + ", ".join(REASON_CODES) +
    ". " + _JSON_ONLY + ' Shape: {"items":[{"window_id":"...","verdict":"accept","confidence":0.0,'
    '"reasons":[{"code":"none","detail":"..."}]}]}')
NARRATOR_SYSTEM = (
    "You are the Narrator. Write one plain sentence (at most 140 characters) telling the listener what "
    "was noticed, quoting the time range and the counts exactly as given, for example: \"You've skipped "
    "1:10-1:25 in 4 of 5 listens.\" No advice, no questions, no exclamation. " + _JSON_ONLY +
    ' Shape: {"items":[{"window_id":"...","sentence":"..."}]}')
INSTRUCTIONS = {"analyst": "Analyse these windows.", "skeptic": "Check these hypotheses.",
                "narrator": "Narrate these insights."}


@dataclass(frozen=True)
class Hypothesis:
    window_id: str
    hypothesis: str
    cause: str
    confidence: float
    source: str = "llm"


@dataclass(frozen=True)
class Reason:
    code: str
    detail: str
    severity: str = "hard"   # hard -> reject, soft -> downgrade
    source: str = "rule"

    def as_dict(self) -> dict:
        return {"code": self.code, "detail": self.detail, "severity": self.severity, "source": self.source}


@dataclass(frozen=True)
class Verdict:
    window_id: str
    verdict: str
    confidence: float
    reasons: tuple[Reason, ...] = ()
    source: str = "llm"


@dataclass(frozen=True)
class Narration:
    window_id: str
    sentence: str
    source: str = "llm"


@dataclass(frozen=True)
class SkepticRules:
    intro_press_ms: int = 3000
    min_sessions: int = 3
    min_skip_sessions: int = 2
    max_session_share: float = 0.5
    max_undo_share: float = 0.08
    shuffle_share: float = 0.75
    min_non_shuffle: int = 2
    min_outside: int = 2
    daypart_share: float = 0.8
    outside_max_rate: float = 0.34
    downgrade_factor: float = 0.5
    full_evidence_sessions: int = 4
    single_daypart_sessions: int = 6


def evidence_cap(ev: WindowEvidence, r: "SkepticRules") -> float:
    """The most confidence the listens support, whatever a model claims."""
    return ev.skip_rate * min(1.0, ev.sessions_skipped / r.full_evidence_sessions)


DEFAULT_RULES = SkepticRules()


def rule_reasons(ev: WindowEvidence, r: SkepticRules = DEFAULT_RULES) -> list[Reason]:
    out: list[Reason] = []
    if ev.run.first_window == 0 or (ev.median_first_press_ms is not None
                                    and ev.median_first_press_ms < r.intro_press_ms):
        out.append(Reason("intro", "skipped from the very start of the track: an intro skip, not a dislike"))
    if ev.sessions_reached < r.min_sessions:
        out.append(Reason("few_listens", f"only {ev.sessions_reached} distinct sessions reached it"))
    if ev.sessions_skipped < r.min_skip_sessions or ev.max_session_share > r.max_session_share:
        out.append(Reason("one_off_session",
                          f"{ev.max_session_share:.0%} of skips came from one session"))
    if ev.undo_share > r.max_undo_share:
        out.append(Reason("undo", f"{ev.undone} of {ev.attempts} skip attempts were undone"))
    if ev.skipped and ev.shuffle_skipped / ev.skipped >= r.shuffle_share:
        if ev.non_shuffle_reached >= r.min_non_shuffle:
            if ev.non_shuffle_skipped / ev.non_shuffle_reached < r.outside_max_rate:
                out.append(Reason("shuffle", f"skipped in shuffle, but kept in {ev.non_shuffle_reached - ev.non_shuffle_skipped} "
                                             f"of {ev.non_shuffle_reached} non-shuffle listens"))
        else:
            out.append(Reason("shuffle", "only heard in shuffle sessions so far", severity="soft"))
    if ev.skipped and ev.top_daypart_share >= r.daypart_share:
        if ev.outside_reached >= r.min_outside and ev.outside_skipped / ev.outside_reached < r.outside_max_rate:
            out.append(Reason("time_of_day",
                              f"skips cluster in the {ev.top_daypart}; kept at other times", severity="soft"))
        elif ev.outside_reached < r.min_outside and ev.sessions_skipped < r.single_daypart_sessions:
            out.append(Reason("time_of_day",
                              f"only {ev.sessions_skipped} sessions, all in the {ev.top_daypart}", severity="soft"))
    return out


def rule_verdict(reasons: Sequence[Reason]) -> str:
    if any(x.severity == "hard" for x in reasons):
        return "reject"
    return "downgrade" if reasons else "accept"


def combine(hyp: Hypothesis, model: Verdict | None, rules: Sequence[Reason],
            r: SkepticRules = DEFAULT_RULES, cap: float = 1.0) -> Verdict:
    """The stricter of the rules and the model; confidence never exceeds the Analyst's or ``cap``."""
    v = rule_verdict(rules)
    conf = min(hyp.confidence, cap)
    reasons = list(rules)
    source = "rules"
    if model is not None:
        source = model.source
        if _SEVERITY[model.verdict] > _SEVERITY[v]:
            v = model.verdict
        conf = min(conf, model.confidence)
        have = {x.code for x in reasons}
        reasons += [x for x in model.reasons if (x.code != "none" or v == "accept") and x.code not in have]
    if v == "downgrade":
        conf *= r.downgrade_factor
    elif v == "reject":
        conf = 0.0
    return Verdict(hyp.window_id, v, round(conf, 4), tuple(reasons), source)


# ------------------------------------------------------------------ fallbacks

def fallback_hypothesis(ev: WindowEvidence) -> Hypothesis:
    ch = next((c for c in ev.changes if c.get("kind") in CAUSES), None)
    cause = ch["kind"] if ch else "unknown"
    text = (f"Skips start where {ch['detail']}." if ch
            else "Skips cluster here; no musical change was detected at this point.")
    conf = ev.skip_rate * min(1.0, ev.sessions_skipped / 4)
    return Hypothesis(ev.window_id, text, cause, round(conf, 4), "fallback")


def fallback_sentence(ev: WindowEvidence) -> str:
    return f"You've skipped {fmt_ms(ev.run.start_ms)}-{fmt_ms(ev.run.end_ms)} in {ev.skipped} of {ev.reached} listens."


_COUNTS = re.compile(r"(\d+)\s+(?:of|out of)\s+(?:your\s+|the\s+)?(?:last\s+)?(\d+)")
_SENTENCE_BREAK = re.compile(r"[.!?]\s+\S")


def sentence_problems(s: str, ev: WindowEvidence) -> list[str]:
    s = s.strip()
    errs = []
    if "\n" in s or len(s) > MAX_SENTENCE:
        errs.append("not one short line")
    if not s.endswith("."):
        errs.append("must end with a period")
    if _SENTENCE_BREAK.search(s[:-1]):
        errs.append("more than one sentence")
    if "?" in s or "!" in s:
        errs.append("no questions or exclamations")
    if fmt_ms(ev.run.start_ms) not in s or fmt_ms(ev.run.end_ms) not in s:
        errs.append("must quote the exact range")
    for m in _COUNTS.finditer(s):
        if (int(m.group(1)), int(m.group(2))) != (ev.skipped, ev.reached):
            errs.append(f"counts {m.group(0)!r} do not match {ev.skipped} of {ev.reached}")
    return errs


# ------------------------------------------------------------------ calls

@dataclass
class RoleResult:
    by_window: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _request(role: str, items: list[dict]) -> dict:
    return {"role": role, "prompt_version": PROMPT_VERSION, "items": items}


def _call(caller: Caller, role: str, system: str, schema: dict, request: dict) -> tuple[dict[str, dict], list[str]]:
    """Valid items by window id, plus problems. Raises only ``BudgetExhausted``."""
    try:
        reply = caller.call(role, system, INSTRUCTIONS[role], request)
    except BudgetExhausted:
        raise
    except Exception as e:  # a failing backend must never break the nightly run
        caller.stats.errors += 1
        return {}, [f"{role}: client error {type(e).__name__}: {e}"]
    try:
        obj = parse_json_object(reply)
    except LLMOutputError as e:
        caller.stats.invalid += 1
        return {}, [f"{role}: {e}"]
    errs = validate(obj, {"type": "object", "required": ["items"], "properties": {"items": {"type": "array"}}})
    if errs:
        caller.stats.invalid += 1
        return {}, [f"{role}: {e}" for e in errs]
    caller.remember(role, system, request, reply)
    wanted = {it["window_id"] for it in request["items"]}
    good: dict[str, dict] = {}
    problems: list[str] = []
    for i, it in enumerate(obj["items"]):
        e = validate(it, schema["properties"]["items"]["items"], f"$.items[{i}]")
        wid = it.get("window_id") if isinstance(it, dict) else None
        if e:
            problems += e
        elif wid not in wanted:
            problems.append(f"$.items[{i}]: unknown window_id {wid!r}")
        elif wid not in good:
            good[wid] = it
    if problems:
        caller.stats.invalid += 1
    return good, [f"{role}: {p}" for p in problems]


def analyst(caller: Caller, evidence: Sequence[WindowEvidence]) -> RoleResult:
    req = _request("analyst", [ev.to_request() for ev in evidence])
    good, errs = _call(caller, "analyst", ANALYST_SYSTEM, ANALYST_SCHEMA, req)
    res = RoleResult(errors=errs)
    for ev in evidence:
        it = good.get(ev.window_id)
        if it is None:
            caller.stats.fallbacks += 1
            res.by_window[ev.window_id] = fallback_hypothesis(ev)
        else:
            res.by_window[ev.window_id] = Hypothesis(ev.window_id, it["hypothesis"].strip(), it["cause"],
                                                     float(it["confidence"]))
    return res


def skeptic(caller: Caller, evidence: Sequence[WindowEvidence], hypotheses: Mapping[str, Hypothesis],
            rules: SkepticRules = DEFAULT_RULES) -> RoleResult:
    """Final verdicts. Windows the rules already reject are decided without the model."""
    res = RoleResult()
    ask = []
    reasons = {ev.window_id: rule_reasons(ev, rules) for ev in evidence}
    for ev in evidence:
        if rule_verdict(reasons[ev.window_id]) == "reject":
            res.by_window[ev.window_id] = combine(hypotheses[ev.window_id], None, reasons[ev.window_id], rules,
                                                  evidence_cap(ev, rules))
        else:
            ask.append(ev)
    if not ask:
        return res
    items = []
    for ev in ask:
        h = hypotheses[ev.window_id]
        items.append(dict(ev.to_request(), hypothesis=h.hypothesis, cause=h.cause, confidence=h.confidence,
                          rule_flags=[x.as_dict() for x in reasons[ev.window_id]]))
    good, errs = _call(caller, "skeptic", SKEPTIC_SYSTEM, SKEPTIC_SCHEMA, _request("skeptic", items))
    res.errors += errs
    for ev in ask:
        it = good.get(ev.window_id)
        model = None
        if it is not None and it["verdict"] != "accept" and not any(x["code"] != "none" for x in it["reasons"]):
            res.errors.append(f"skeptic: {ev.window_id}: {it['verdict']} without an explicit reason")
            caller.stats.invalid += 1
            it = None
        if it is None:
            caller.stats.fallbacks += 1
        else:
            model = Verdict(ev.window_id, it["verdict"], float(it["confidence"]),
                            tuple(Reason(x["code"], x["detail"].strip(),
                                         "soft" if it["verdict"] == "downgrade" else "hard", "llm")
                                  for x in it["reasons"]))
        res.by_window[ev.window_id] = combine(hypotheses[ev.window_id], model, reasons[ev.window_id], rules,
                                              evidence_cap(ev, rules))
    return res


def narrator(caller: Caller, evidence: Sequence[WindowEvidence]) -> RoleResult:
    req = _request("narrator", [{"window_id": ev.window_id, "start": fmt_ms(ev.run.start_ms),
                                 "end": fmt_ms(ev.run.end_ms), "listens_skipped": ev.skipped,
                                 "listens_reached": ev.reached} for ev in evidence])
    good, errs = _call(caller, "narrator", NARRATOR_SYSTEM, NARRATOR_SCHEMA, req)
    res = RoleResult(errors=errs)
    for ev in evidence:
        it = good.get(ev.window_id)
        if it is not None:
            problems = sentence_problems(it["sentence"], ev)
            if problems:
                res.errors.append(f"narrator: {ev.window_id}: {'; '.join(problems)}")
                caller.stats.invalid += 1
                it = None
        if it is None:
            caller.stats.fallbacks += 1
            res.by_window[ev.window_id] = Narration(ev.window_id, fallback_sentence(ev), "fallback")
        else:
            res.by_window[ev.window_id] = Narration(ev.window_id, it["sentence"].strip())
    return res

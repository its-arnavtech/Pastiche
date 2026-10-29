"""The nightly insight pipeline: skip candidates in, at most about one plain-language insight out per day.

``run_nightly`` is pure apart from the model call: ``(events, state, llm, now) -> (new state, report)``.
It never touches playback and has no delivery channel other than the passive inbox. The nightly job
that schedules it and persists ``InsightState`` belongs to the core (T-029).

Order of a night, cheapest first. Every step before the model can drop a window.

1. Apply new answer events (``insight_yes|no|unsure``): lifecycle transition plus threshold tuning, logged.
2. Statistical detector (T-014) with this user's tuned ``min_skip_rate``; adjacent windows merge into runs.
3. Skip runs that overlap an existing insight; overlapping a dismissed one counts as suppressed.
4. 3-listen rule: at least ``min_window_listens`` listens must have reached the run.
5. Rejected or held runs are not re-asked until ``recheck_after_listens`` more listens of the track.
6. Deterministic confound rules (``roles.rule_reasons``); hard failures are rejected without a call.
7. Per track, one Analyst call, one Skeptic call and (for survivors) one Narrator call, cached by input
   hash and charged to the daily budget. Out of budget means deferred to the next night.
8. Accepted runs whose confidence meets the tuned threshold become ``proposed``; delivery moves at most
   ``max_new_per_day`` of them to ``shown`` (the inbox).
"""
from __future__ import annotations

import copy
import dataclasses
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from remixer.analytics.events import Event, INSIGHT_EVENT_TYPES
from remixer.analytics.heatmap import DetectorConfig
from remixer.analytics.interpret import DEFAULT_CONFIG, InterpretConfig
from remixer.fatigue.insights import ANSWERS

from . import lifecycle
from .cost import BudgetExhausted, CallBudget, Caller, ResponseCache
from .evidence import History, TrackFeatures, WindowEvidence, local_day, runs_from_candidates
from .lifecycle import DEFAULT_LIFECYCLE, InsightRecord, LifecycleConfig
from .llm import LLMClient
from .roles import DEFAULT_RULES, SkepticRules, analyst, narrator, rule_reasons, rule_verdict, skeptic
from .tuning import DEFAULT_TUNING, ThresholdChange, Thresholds, TuningConfig, apply_answer


@dataclass(frozen=True)
class InsightConfig:
    utc_offset_minutes: int = 0
    min_window_listens: int = 3
    daily_call_budget: int = 30
    max_windows_per_call: int = 8
    recheck_after_listens: int = 3
    min_skips: int = 2
    max_undo_rate: float = 0.2
    rules: SkepticRules = DEFAULT_RULES
    lifecycle: LifecycleConfig = DEFAULT_LIFECYCLE
    tuning: TuningConfig = DEFAULT_TUNING
    interpret: InterpretConfig = DEFAULT_CONFIG

    def detector(self, th: Thresholds) -> DetectorConfig:
        return DetectorConfig(min_track_listens=self.min_window_listens, min_skips=self.min_skips,
                              min_skip_rate=th.min_skip_rate(self.tuning), max_undo_rate=self.max_undo_rate)


DEFAULT_INSIGHTS = InsightConfig()


@dataclass(frozen=True)
class Rejection:
    window_id: str
    track_listens: int
    verdict: str          # reject | downgrade | below_threshold
    reasons: tuple[str, ...]
    day: str


@dataclass
class InsightState:
    """Everything one user's pipeline remembers between nights; JSON round-trips."""
    records: dict[str, InsightRecord] = field(default_factory=dict)
    thresholds: Thresholds = field(default_factory=Thresholds)
    threshold_log: list[ThresholdChange] = field(default_factory=list)
    applied_answers: set[str] = field(default_factory=set)
    rejections: dict[str, Rejection] = field(default_factory=dict)
    cache: ResponseCache = field(default_factory=ResponseCache)
    budget_used: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "records": {k: r.to_dict() for k, r in sorted(self.records.items())},
            "thresholds": dict(sorted(self.thresholds.values.items())),
            "threshold_log": [dataclasses.asdict(c) for c in self.threshold_log],
            "applied_answers": sorted(self.applied_answers),
            "rejections": {k: dataclasses.asdict(r) for k, r in sorted(self.rejections.items())},
            "cache": dict(sorted(self.cache.entries.items())),
            "budget_used": dict(sorted(self.budget_used.items())),
        }, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str) -> "InsightState":
        d = json.loads(text)
        return cls(
            records={k: InsightRecord.from_dict(v) for k, v in d["records"].items()},
            thresholds=Thresholds(dict(d["thresholds"])),
            threshold_log=[ThresholdChange(**c) for c in d["threshold_log"]],
            applied_answers=set(d["applied_answers"]),
            rejections={k: Rejection(**dict(v, reasons=tuple(v["reasons"]))) for k, v in d["rejections"].items()},
            cache=ResponseCache(dict(d["cache"])),
            budget_used=dict(d["budget_used"]),
        )

    def inbox(self) -> list[InsightRecord]:
        """What the inbox lists: everything delivered at least once, newest first."""
        shown = [r for r in self.records.values() if r.shown_day is not None]
        return sorted(shown, key=lambda r: (r.shown_day, r.insight_id), reverse=True)

    def selection_insights(self):
        return lifecycle.selection_insights(self.records.values())


@dataclass
class NightlyReport:
    day: str
    candidates: int = 0
    known: int = 0
    suppressed: int = 0
    waiting: int = 0
    recheck_later: int = 0
    rule_rejected: int = 0
    model_rejected: int = 0
    downgraded: int = 0
    below_threshold: int = 0
    deferred: int = 0
    proposed: list[str] = field(default_factory=list)
    delivered: list[str] = field(default_factory=list)
    answers_applied: int = 0
    threshold_changes: list[ThresholdChange] = field(default_factory=list)
    llm: dict = field(default_factory=dict)
    decisions: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def apply_answers(state: InsightState, events: Iterable[Event], cfg: InsightConfig = DEFAULT_INSIGHTS,
                  until_ms: int | None = None) -> tuple[int, list[ThresholdChange]]:
    """Apply unseen answer events to ``state`` in place, oldest first. Returns (applied, changes)."""
    todo = sorted((e for e in events if e.event_type in INSIGHT_EVENT_TYPES
                   and e.event_id not in state.applied_answers
                   and (until_ms is None or e.wall_time <= until_ms)),
                  key=lambda e: (e.wall_time, e.event_id))
    changes: list[ThresholdChange] = []
    n = 0
    for e in todo:
        state.applied_answers.add(e.event_id)
        rec = state.records.get((e.payload or {}).get("insight_id"))
        if rec is None:
            continue
        value = ANSWERS[e.event_type]
        day = local_day(e.wall_time, cfg.utc_offset_minutes)
        state.records[rec.insight_id] = lifecycle.answer(rec, value, day, cfg.lifecycle)
        state.thresholds, ch = apply_answer(state.thresholds, value, cause=rec.cause, track_id=rec.track_id,
                                            insight_id=rec.insight_id, day=day, cfg=cfg.tuning)
        changes += ch
        n += 1
    state.threshold_log += changes
    return n, changes


def _chunks(items: list, n: int) -> Iterable[list]:
    for i in range(0, len(items), n):
        yield items[i:i + n]


def run_nightly(events: Iterable[Event], state: InsightState, llm: LLMClient, now_ms: int,
                features: TrackFeatures | None = None, cfg: InsightConfig = DEFAULT_INSIGHTS
                ) -> tuple[InsightState, NightlyReport]:
    events = [e for e in events if e.wall_time <= now_ms]
    st = copy.deepcopy(state)
    day = local_day(now_ms, cfg.utc_offset_minutes)
    rep = NightlyReport(day)
    rep.answers_applied, rep.threshold_changes = apply_answers(st, events, cfg)

    hist = History(events, cfg.interpret)
    runs = runs_from_candidates(hist.heatmap.candidates(cfg.detector(st.thresholds)))
    rep.candidates = len(runs)
    todo: list[WindowEvidence] = []
    for run in runs:
        overlapping = [r for r in st.records.values()
                       if r.overlaps(run.track_id, run.track_version, run.start_ms, run.end_ms)]
        if overlapping:
            if any(r.state == "dismissed" for r in overlapping):
                rep.suppressed += 1
            else:
                rep.known += 1
            continue
        memo = st.rejections.get(run.window_id)
        if memo and run.track_listens < memo.track_listens + cfg.recheck_after_listens:
            rep.recheck_later += 1
            continue
        ev = hist.evidence(run, cfg.utc_offset_minutes, features)
        if ev.reached < cfg.min_window_listens:
            rep.waiting += 1
            continue
        reasons = rule_reasons(ev, cfg.rules)
        if rule_verdict(reasons) == "reject":
            rep.rule_rejected += 1
            st.rejections[run.window_id] = Rejection(run.window_id, run.track_listens, "reject",
                                                     tuple(x.code for x in reasons), day)
            rep.decisions.append({"window_id": run.window_id, "stage": "rules", "verdict": "reject",
                                  "reasons": [x.code for x in reasons]})
            continue
        todo.append(ev)

    caller = Caller(llm, st.cache, CallBudget(cfg.daily_call_budget, st.budget_used), day)
    by_track: dict[tuple[str, str], list[WindowEvidence]] = {}
    for ev in todo:
        by_track.setdefault(ev.run.key, []).append(ev)
    for key in sorted(by_track):
        for chunk in _chunks(by_track[key], cfg.max_windows_per_call):
            keep = None
            try:
                hyps = analyst(caller, chunk)
                verdicts = skeptic(caller, chunk, hyps.by_window, cfg.rules)
                rep.errors += hyps.errors + verdicts.errors
                keep = []
                for ev in chunk:
                    v, h = verdicts.by_window[ev.window_id], hyps.by_window[ev.window_id]
                    need = st.thresholds.surface(h.cause, ev.run.track_id, cfg.tuning)
                    outcome = v.verdict if v.verdict != "accept" else (
                        "accept" if v.confidence >= need else "below_threshold")
                    rep.decisions.append({"window_id": ev.window_id, "stage": v.source, "verdict": outcome,
                                          "confidence": v.confidence, "threshold": need,
                                          "reasons": [x.code for x in v.reasons if x.code != "none"]})
                    if outcome == "accept":
                        keep.append((ev, h, v))
                        continue
                    if outcome == "reject":
                        rep.model_rejected += 1
                    elif outcome == "downgrade":
                        rep.downgraded += 1
                    else:
                        rep.below_threshold += 1
                    st.rejections[ev.window_id] = Rejection(
                        ev.window_id, ev.run.track_listens, outcome,
                        tuple(x.code for x in v.reasons if x.code != "none"), day)
                if not keep:
                    continue
                told = narrator(caller, [ev for ev, _, _ in keep])
                rep.errors += told.errors
            except BudgetExhausted:
                rep.deferred += len(chunk) if keep is None else len(keep)
                continue
            for ev, h, v in keep:
                st.rejections.pop(ev.window_id, None)
                st.records[ev.window_id] = InsightRecord(
                    insight_id=ev.window_id, track_id=ev.run.track_id, track_version=ev.run.track_version,
                    start_ms=ev.run.start_ms, end_ms=ev.run.end_ms, sentence=told.by_window[ev.window_id].sentence,
                    hypothesis=h.hypothesis, cause=h.cause, confidence=v.confidence, skipped=ev.skipped,
                    reached=ev.reached, proposed_day=day)
                rep.proposed.append(ev.window_id)
    st.budget_used = caller.budget.used
    st.records, rep.delivered = lifecycle.deliver(st.records, day, cfg.lifecycle)
    rep.llm = caller.stats.as_dict()
    return st, rep


def inbox_view(state: InsightState, titles: Mapping[str, Mapping[str, Any]] | None = None) -> list[dict]:
    """JSON rows for the player's inbox (``GET /api/insights``)."""
    titles = titles or {}
    out = []
    for r in state.inbox():
        t = titles.get(r.track_id, {})
        out.append({"insight_id": r.insight_id, "track_id": r.track_id, "track_version": r.track_version,
                    "title": t.get("title", r.track_id), "source_kind": t.get("source_kind", "source"),
                    "start_ms": r.start_ms, "end_ms": r.end_ms, "hypothesis": r.sentence, "why": r.hypothesis,
                    "state": r.state, "answer": r.answer, "confirmed": r.state == "confirmed",
                    "pending": r.pending, "ask_again_on": r.ask_again_on, "shown_day": r.shown_day})
    return out

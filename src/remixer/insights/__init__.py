"""Insight agent layer (T-027): skip candidates become plain-language insights in a passive inbox.

Analyst, Skeptic and Narrator are pure functions around a batched ``LLMClient`` call with
schema-validated JSON output and deterministic fallbacks. The nightly pipeline gates every call
behind the T-014 detector and the confound rules, caches by input hash and respects a daily budget.
Stdlib only on top of ``remixer.analytics`` and ``remixer.fatigue``.
"""
from .cost import CallBudget, CallStats, Caller, ResponseCache
from .evidence import History, StaticFeatures, TrackFeatures, WindowEvidence, WindowFeatures
from .lifecycle import InsightRecord, LifecycleConfig, selection_insights
from .llm import LLMClient, MockLLM
from .pipeline import (
    DEFAULT_INSIGHTS, InsightConfig, InsightState, NightlyReport, apply_answers, inbox_view, run_nightly,
)
from .roles import SkepticRules, analyst, narrator, skeptic
from .schema import LLMOutputError, validate
from .tuning import Bound, Thresholds, TuningConfig, step

__all__ = [
    "Bound", "CallBudget", "CallStats", "Caller", "DEFAULT_INSIGHTS", "History", "InsightConfig",
    "InsightRecord", "InsightState", "LLMClient", "LLMOutputError", "LifecycleConfig", "MockLLM",
    "NightlyReport", "ResponseCache", "SkepticRules", "StaticFeatures", "Thresholds", "TrackFeatures",
    "TuningConfig", "WindowEvidence", "WindowFeatures", "analyst", "apply_answers", "inbox_view",
    "narrator", "run_nightly", "selection_insights", "skeptic", "step", "validate",
]

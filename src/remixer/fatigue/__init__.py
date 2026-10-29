"""Fatigue model, credit assignment, attribution and selection weights (T-015).

Ratings are user-initiated only: nothing in this package asks the user for anything.
``attribution`` needs numpy (``analytics`` extra); everything else is stdlib-only.
"""
from .credit import CreditConfig, StemUse, assign_credit, loudness_shares
from .insights import Insight, answer, apply_answer_events, confirmed, insights_from_candidates
from .propagation import neighbor_penalties
from .selection import (
    SelectionConfig, StemCandidate, candidate_weight, novelty_bonus, select_batch, selection_weight,
    source_cap,
)
from .state import FatigueConfig, FatigueModel, replay, track_shares

__all__ = [
    "CreditConfig", "StemUse", "assign_credit", "loudness_shares",
    "Insight", "answer", "apply_answer_events", "confirmed", "insights_from_candidates",
    "neighbor_penalties",
    "SelectionConfig", "StemCandidate", "candidate_weight", "novelty_bonus", "select_batch",
    "selection_weight", "source_cap",
    "FatigueConfig", "FatigueModel", "replay", "track_shares",
]

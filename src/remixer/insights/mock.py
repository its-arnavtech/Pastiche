"""Deterministic scripts for ``MockLLM``: a plausible responder and two adversaries.

``heuristic_script`` answers like a careful model would, but only from the request JSON. The
pipeline must stay correct with ``always_accept_script`` (an overconfident model) and with
``garbage_script`` (malformed output). Tests use all three. The mock backend for the web player
uses the heuristic one.
"""
from __future__ import annotations

from typing import Any

from .llm import by_role, items_of


def _analyst(request: dict, system: str | None) -> dict:
    out = []
    for it in items_of(request):
        ch = (it.get("changes") or [{}])[0]
        cause = ch.get("kind", "unknown")
        text = (f"The skip lines up with {ch['detail']}." if ch.get("detail")
                else "Skips cluster here without a clear musical change.")
        conf = it["skip_rate"] * min(1.0, it["sessions_skipped"] / 4)
        out.append({"window_id": it["window_id"], "hypothesis": text, "cause": cause,
                    "confidence": round(conf, 3)})
    return {"items": out}


def _skeptic(request: dict, system: str | None) -> dict:
    out = []
    for it in items_of(request):
        reasons = []
        ns_reached = it["listens_reached"] - it["shuffle_listens_reached"]
        ns_skipped = it["listens_skipped"] - it["shuffle_listens_skipped"]
        if it["listens_skipped"] and it["shuffle_listens_skipped"] / it["listens_skipped"] >= 0.75 \
                and ns_reached >= 2 and ns_skipped / ns_reached < 0.34:
            reasons.append({"code": "shuffle", "detail": "kept outside shuffle sessions"})
        if it["top_daypart_share"] >= 0.8 and it["listens_outside_top_daypart"] >= 2 \
                and it["skips_outside_top_daypart"] / it["listens_outside_top_daypart"] < 0.34:
            reasons.append({"code": "time_of_day", "detail": f"skips only in the {it['top_daypart_of_skips']}"})
        if it["undo_share"] > 0.08:
            reasons.append({"code": "undo", "detail": "several skips were undone"})
        if it["sessions_reached"] < 3:
            reasons.append({"code": "few_listens", "detail": "too few sessions"})
        verdict = "reject" if any(r["code"] in ("shuffle", "undo", "few_listens") for r in reasons) else (
            "downgrade" if reasons else "accept")
        if not reasons:
            reasons = [{"code": "none", "detail": f"no confound in {it['listens_reached']} listens "
                                                  f"over {it['sessions_reached']} sessions"}]
        out.append({"window_id": it["window_id"], "verdict": verdict,
                    "confidence": round(min(1.0, it["confidence"] + 0.05), 3), "reasons": reasons})
    return {"items": out}


def _narrator(request: dict, system: str | None) -> dict:
    return {"items": [{"window_id": it["window_id"],
                       "sentence": f"You've skipped {it['start']}-{it['end']} in {it['listens_skipped']} "
                                   f"of {it['listens_reached']} listens."} for it in items_of(request)]}


heuristic_script = by_role(analyst=_analyst, skeptic=_skeptic, narrator=_narrator)


def _accept_all(request: dict, system: str | None) -> dict:
    return {"items": [{"window_id": it["window_id"], "verdict": "accept", "confidence": 1.0,
                       "reasons": [{"code": "none", "detail": "looks real"}]} for it in items_of(request)]}


def _overclaim(request: dict, system: str | None) -> dict:
    return {"items": [{"window_id": it["window_id"], "hypothesis": "You hate this part.", "cause": "unknown",
                       "confidence": 1.0} for it in items_of(request)]}


always_accept_script = by_role(analyst=_overclaim, skeptic=_accept_all, narrator=_narrator)

GARBAGE: tuple[Any, ...] = (
    "", "not json at all", "{\"items\": [", "[1, 2, 3]", "{\"answer\": 42}", "{\"items\": \"none\"}",
    "```json\n{\"items\": [{\"window_id\": 7}]}\n```", "null", "{\"items\": [{\"confidence\": \"high\"}]}",
)


def garbage_script(request: dict, system: str | None) -> Any:
    n = len(request.get("items", [])) + len(request.get("role", ""))
    return GARBAGE[n % len(GARBAGE)]

"""Evaluate the insight pipeline on the confound world: quality, call counts, budget and cache.

``uv run python -m remixer.insights.evaluate --seeds 5`` prints one JSON report. Every number in the
T-027 changelog comes from it.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace

from .llm import MockLLM
from .mock import always_accept_script, garbage_script, heuristic_script
from .pipeline import InsightConfig, InsightState, run_nightly
from .scenarios import CONFOUNDS, confound_world, score

SCRIPTS = {"heuristic": heuristic_script, "always_accept": always_accept_script, "garbage": garbage_script}


def season(world, script, cfg: InsightConfig, state: InsightState | None = None):
    st = state or InsightState()
    llm = MockLLM(script)
    nights = []
    for now in world.night_ends():
        st, rep = run_nightly(world.events, st, llm, now, world.features, cfg)
        nights.append(rep)
    return st, nights, llm


def _sum(nights, key):
    return sum(r.llm.get(key, 0) for r in nights)


def evaluate(seeds: int = 5, budget: int = 30, tight_budget: int = 6) -> dict:
    out: dict = {"seeds": seeds, "daily_call_budget": budget, "variants": {}}
    t0 = time.perf_counter()
    for name, script in SCRIPTS.items():
        tot = {"surfaced": 0, "true_positive": 0, "dislikes": 0, "dislikes_found": 0}
        kinds: dict[str, int] = {}
        calls = cache_hits = windows = invalid = fallbacks = candidates = rules = max_night = 0
        by_role: dict[str, int] = {}
        for seed in range(seeds):
            w = confound_world(seed=seed)
            cfg = InsightConfig(utc_offset_minutes=w.utc_offset_minutes, daily_call_budget=budget)
            st, nights, _ = season(w, script, cfg)
            s = score(st.records.values(), w)
            for k in tot:
                tot[k] += s[k]
            for k, v in s["surfaced_by_kind"].items():
                kinds[k] = kinds.get(k, 0) + v
            calls += _sum(nights, "calls")
            cache_hits += _sum(nights, "cache_hits")
            windows += _sum(nights, "windows_sent")
            invalid += _sum(nights, "invalid")
            fallbacks += _sum(nights, "fallbacks")
            max_night = max([max_night] + [r.llm["calls"] for r in nights])
            for r in nights:
                for k, v in r.llm["by_role"].items():
                    by_role[k] = by_role.get(k, 0) + v
            candidates += sum(r.candidates - r.known - r.suppressed for r in nights)
            rules += sum(r.rule_rejected for r in nights)
        out["variants"][name] = {
            "precision": round(tot["true_positive"] / tot["surfaced"], 4) if tot["surfaced"] else 1.0,
            "recall": round(tot["dislikes_found"] / tot["dislikes"], 4),
            **tot, "surfaced_by_kind": dict(sorted(kinds.items())),
            "confounds_surfaced": sum(kinds.get(k, 0) for k in CONFOUNDS),
            "llm_calls": calls, "llm_calls_by_role": dict(sorted(by_role.items())), "cache_hits": cache_hits,
            "windows_sent": windows, "invalid_replies": invalid, "fallback_items": fallbacks,
            "max_calls_in_a_night": max_night, "calls_per_seed_season": round(calls / seeds, 1),
            "new_candidate_evaluations": candidates, "rejected_by_rules_without_a_call": rules,
        }

    w = confound_world(seed=0)
    cfg = InsightConfig(utc_offset_minutes=w.utc_offset_minutes, daily_call_budget=budget)
    st, nights, _ = season(w, heuristic_script, cfg)
    again, rep = run_nightly(w.events, st, MockLLM(heuristic_script), w.night_ends()[-1], w.features, cfg)
    warm = InsightState(cache=st.cache)
    _, warm_nights, warm_llm = season(w, heuristic_script, cfg, warm)
    tight_cfg = replace(cfg, daily_call_budget=tight_budget)
    tst, tnights, _ = season(w, heuristic_script, tight_cfg)
    out["cache_and_budget_seed0"] = {
        "season_calls": _sum(nights, "calls"),
        "same_night_rerun_calls": rep.llm["calls"],
        "replay_with_warm_cache_calls": len(warm_llm.calls),
        "replay_with_warm_cache_hits": _sum(warm_nights, "cache_hits"),
        "tight_budget": tight_budget,
        "tight_budget_deferred_windows": sum(r.deferred for r in tnights),
        "tight_budget_max_calls_in_a_night": max(r.llm["calls"] for r in tnights),
        "tight_budget_score": score(tst.records.values(), w),
        "insights_shown_per_day_max": max(len(r.delivered) for r in nights),
    }
    out["seconds"] = round(time.perf_counter() - t0, 2)
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--budget", type=int, default=30)
    ap.add_argument("--tight-budget", type=int, default=6)
    a = ap.parse_args(argv)
    print(json.dumps(evaluate(a.seeds, a.budget, a.tight_budget), indent=2))


if __name__ == "__main__":
    main()

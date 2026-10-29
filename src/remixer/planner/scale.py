"""Scale run: plan many recipes over a large synthetic library, then ban the most-used song.

Run: ``python -m remixer.planner.scale --stems 50000 --recipes 10000``.
Reports wall times per stage, peak RSS and the patch footprint as JSON.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter

from remixer.fatigue.state import FatigueModel

from .exclusions import SongBan
from .library import synthetic_library
from .lineage import LineageIndex
from .plan import Planner, plan_and_store
from .store import InMemoryRecipeStore

STEMS_PER_SONG = 3.8   # drums, bass, other and 80 percent vocals


def _taste(stem_id: str) -> float:
    return 0.2 + 0.8 * hashlib.sha256(stem_id.encode()).digest()[0] / 255


def _rss_mb() -> float:
    if sys.platform == "win32":  # no `resource` module on Windows; psutil exposes the peak working set
        import psutil

        return psutil.Process().memory_info().peak_wset / (1024 * 1024)
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


def run_scale(n_stems: int = 50_000, n_recipes: int = 10_000, batch_size: int = 100, seed: int = 7) -> dict:
    out: dict = {"target_stems": n_stems, "recipes": n_recipes, "batch_size": batch_size}
    t = time.perf_counter()
    lib = synthetic_library(int(round(n_stems / STEMS_PER_SONG)), seed=seed)
    out["stems"], out["library_s"] = len(lib), round(time.perf_counter() - t, 2)
    out["rss_after_library_mb"] = round(_rss_mb(), 1)

    t = time.perf_counter()
    planner = Planner(lib, lib, _taste, FatigueModel(), 0.0)
    out["planner_init_s"] = round(time.perf_counter() - t, 2)

    store, lineage = InMemoryRecipeStore(), LineageIndex()
    ledger: dict = {}
    unfilled = slots = 0
    t = time.perf_counter()
    for b in range((n_recipes + batch_size - 1) // batch_size):
        n = min(batch_size, n_recipes - b * batch_size)
        batch = plan_and_store(planner, n, seed * 1_000_003 + b, store, lineage, ledger)
        ledger, unfilled, slots = batch.ledger, unfilled + batch.unfilled_slots, slots + batch.slots
    plan_s = time.perf_counter() - t
    out["plan_s"] = round(plan_s, 2)
    out["recipes_per_s"] = round(n_recipes / plan_s, 1)
    out["slot_fill_rate"] = round(1 - unfilled / slots, 4)
    out["songs_used"] = len(ledger)
    out["rss_after_plan_mb"] = round(_rss_mb(), 1)

    song, uses = Counter(ledger).most_common(1)[0]
    out["banned_song"], out["banned_song_stem_uses"] = song, uses
    t = time.perf_counter()
    patches = planner.ban(SongBan(song), store, lineage)
    out["patch_s"] = round(time.perf_counter() - t, 3)
    out["patched_recipes"] = len(patches)
    out["rerender_sections"] = sum(len(p.rerender) for p in patches)
    out["needs_regeneration_sections"] = sum(len(p.needs_regeneration) for p in patches)
    out["untouched_sections_in_patched"] = sum(len(p.new.sections) - len(p.rerender) - len(p.needs_regeneration)
                                               for p in patches)
    out["ban_leaks"] = sum(1 for r in store.heads() if song in r.songs)
    out["rss_peak_mb"] = round(_rss_mb(), 1)
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stems", type=int, default=50_000)
    ap.add_argument("--recipes", type=int, default=10_000)
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    print(json.dumps(run_scale(a.stems, a.recipes, a.batch, a.seed), indent=2))


if __name__ == "__main__":
    main()

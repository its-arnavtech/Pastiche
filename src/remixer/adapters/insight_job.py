"""Nightly insight job (T-029, decision 0020): run ``insights.pipeline.run_nightly`` once per local night.

- Loads ``InsightState`` from ``<data>/insights/state.json``, reads playback events up to ``now``, calls
  ``run_nightly`` with the profile's LLM (Ollama, T-028) and a catalog-backed ``TrackFeatures``, and
  writes the new state atomically plus the night's report under ``<data>/insights/nights/``.
- A model that is down (``available()`` false) skips the night; the stored state is left untouched.
- Re-running the same night is safe: the pipeline's response cache answers repeated requests without
  model calls.
- ``due()`` says whether tonight's run is still pending (after ``NIGHT_HOUR`` local, not yet run today);
  ``remixer insights nightly`` runs it from a scheduler. Playback is never touched.

Tenant scope is the profile's data directory (one per tenant in the local profile).
"""
from __future__ import annotations

import dataclasses
import json
import os
import time
from pathlib import Path
from typing import Sequence

from remixer.analytics.events import Event
from remixer.insights.evidence import TrackFeatures, WindowFeatures, local_day
from remixer.insights.pipeline import InsightConfig, InsightState, run_nightly

NIGHT_HOUR = 3            # local hour after which the night's run is due
WINDOW_S = 5.0


def local_offset_minutes(now_s: float | None = None) -> int:
    return int(time.localtime(now_s).tm_gmtoff // 60)


def _dir(adapters) -> Path:
    d = Path(adapters.profile.data_dir) / "insights"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def load_state(adapters) -> InsightState:
    f = _dir(adapters) / "state.json"
    return InsightState.from_json(f.read_text(encoding="utf-8")) if f.exists() else InsightState()


def last_run_day(adapters) -> str | None:
    f = _dir(adapters) / "last_run.json"
    return json.loads(f.read_text(encoding="utf-8")).get("day") if f.exists() else None


def due(adapters, now_ms: int | None = None, utc_offset_minutes: int | None = None) -> bool:
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    off = local_offset_minutes(now_ms / 1000) if utc_offset_minutes is None else utc_offset_minutes
    local_hour = ((now_ms // 60_000 + off) // 60) % 24
    return local_hour >= NIGHT_HOUR and last_run_day(adapters) != local_day(now_ms, off)


class CatalogTrackFeatures:
    """``TrackFeatures`` from the catalog. A generated track (``track_version`` is a recipe id) gets its
    5-second windows from the recipe: section tempo, section index and the stem roles playing. A source
    track gets tempo and per-window loudness from its ``analysis`` row (``meta.window_lufs``)."""

    def __init__(self, catalog, recipes=None):
        self.cat = catalog
        self.recipes = recipes

    def window_features(self, track_id: str, track_version: str) -> Sequence[WindowFeatures] | None:
        if self.recipes is not None:
            try:
                return self._from_recipe(self.recipes.get(track_version))
            except KeyError:
                pass
        rows = self.cat.query("SELECT tempo, meta FROM analysis WHERE owner_id=? ORDER BY model_version DESC LIMIT 1",
                              (track_id,))
        if not rows:
            return None
        meta = json.loads(rows[0]["meta"] or "{}")
        lufs = meta.get("window_lufs") or []
        if not lufs:
            return None
        return [WindowFeatures(i, loudness_lufs=v, tempo_bpm=rows[0]["tempo"]) for i, v in enumerate(lufs)]

    @staticmethod
    def _from_recipe(recipe) -> list[WindowFeatures]:
        end_ms = max(s.end_ms for s in recipe.sections)
        out = []
        for i in range(int(end_ms // (WINDOW_S * 1000)) + (1 if end_ms % (WINDOW_S * 1000) else 0)):
            a, b = int(i * WINDOW_S * 1000), int((i + 1) * WINDOW_S * 1000)
            sec = next((s for s in recipe.sections if s.start_ms <= a < s.end_ms), recipe.sections[-1])
            roles = frozenset(p.role for p in recipe.placements if p.dst_start_ms < b and p.dst_end_ms > a)
            out.append(WindowFeatures(i, tempo_bpm=sec.tempo_bpm, section=f"section {sec.index}", stems=roles))
        return out


def run_job(adapters, now_ms: int | None = None, llm=None, features: TrackFeatures | None = None,
            cfg: InsightConfig | None = None) -> dict:
    """One night for this tenant. Returns the night's report as a dict (``skipped`` set when it did not run)."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    cfg = cfg or InsightConfig(utc_offset_minutes=local_offset_minutes(now_ms / 1000))
    day = local_day(now_ms, cfg.utc_offset_minutes)
    llm = llm if llm is not None else adapters.llm
    if not llm.available():
        return {"day": day, "skipped": "llm unavailable"}
    if features is None:
        from remixer.adapters.planner_catalog import SqliteRecipeStore

        features = CatalogTrackFeatures(adapters.catalog, SqliteRecipeStore(adapters.catalog))
    events = [Event.from_row(r) for r in adapters.events.read("playback")]
    state, report = run_nightly(events, load_state(adapters), llm, now_ms, features, cfg)
    d = _dir(adapters)
    _atomic_write(d / "state.json", state.to_json())
    out = dataclasses.asdict(report)
    (d / "nights").mkdir(exist_ok=True)
    _atomic_write(d / "nights" / f"{day}.json", json.dumps(out, indent=2, default=str))
    _atomic_write(d / "last_run.json", json.dumps({"day": day, "now_ms": now_ms}))
    return out


# ------------------------------------------------------------------ CLI

def cmd_nightly(args) -> int:
    from remixer.adapters import build

    a = build()
    if not args.force and not due(a):
        print(json.dumps({"skipped": "not due", "last_run_day": last_run_day(a)}))
        return 0
    print(json.dumps(run_job(a), default=str))
    return 0


def register(sub) -> None:
    p = sub.add_parser("insights", help="nightly insight job (T-029)")
    s = p.add_subparsers(dest="insights_cmd", required=True)
    n = s.add_parser("nightly", help=f"run tonight's insight pass if due (after {NIGHT_HOUR}:00 local, once a night)")
    n.add_argument("--force", action="store_true", help="run even if tonight's pass already ran")
    n.set_defaults(fn=cmd_nightly)

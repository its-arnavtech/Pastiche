"""Recipe planner: seeded, compatibility-aware batch planning and ban-and-replace patches.

Everything is a pure function of (catalog, taste, fatigue state, confirmed insights, exclusions,
config, seed). Defaults and their reasons are in decision 0012.

Planning a batch of ``n`` recipes:
1. Per recipe, an *anchor* stem (any non-drum stem) is drawn by Gumbel-max over
   ``selection weight x diversity``; its tempo, key and meter become the recipe target.
2. Each section (``sections`` of ``bars_per_section`` bars, target energy from ``energy_curve``)
   fills one slot per role. Candidates are the compatible stems (``compat.py``), weighted
   ``selection_weight x fit x diversity``, ranked by Gumbel top-k with hashed noise
   (``sampling.py``), and the first one with a usable source range wins.
3. A source range is usable when it starts on a source downbeat, fits the stem, does not reuse a
   5-second source window already used by another section of the recipe, and does not overlap a
   *confirmed* insight on that song (``fatigue.selection.blocked_by_insight``; unconfirmed ones
   are ignored there).
4. Batch rules: a song contributes at most ``source_cap(slots)`` stems (``fatigue.selection``,
   about 5 percent of the batch's stem slots); diversity ``1 / (1 + a x uses_in_batch + b x uses_before)``
   spreads use across the library and across batches (the ``ledger``).

The selection weight is ``fatigue.selection.candidate_weight`` (taste x (1 - fatigue) x novelty,
zero for disliked stems or songs), computed once per stem.

Ban-and-replace (``Planner.ban``): resolve the exclusion to stems, find affected *current* recipes
through the lineage index, and for each one replace only the banned placements in only the
sections that contain them. Replacements are ranked deterministically (no noise) by
``similarity^p x fit x selection weight`` against the removed stem, under every rule above;
with no acceptable candidate the section is marked ``needs_regeneration``. The result is a new
version that supersedes the old one; untouched sections keep their hash.
"""
from __future__ import annotations

import dataclasses
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Sequence

import numpy as np

from remixer.fatigue.insights import Insight
from remixer.fatigue.selection import (
    DEFAULT_SELECTION, SelectionConfig, StemCandidate, blocked_by_insight, candidate_weight, source_cap,
)
from remixer.fatigue.state import FatigueModel

from .catalog import NeighborQuery, StemCatalog, StemMeta
from .compat import DEFAULT_COMPAT, CandidateIndex, CompatConfig, Target, positions, section_length_ms, \
    source_length_ms
from .exclusions import Exclusion, ExclusionSet, SongBan, exclusion_id
from .lineage import Lineage
from .model import (
    PLANNER_VERSION, ROLES, WINDOW_MS, Placement, Recipe, Section, canonical_json, changed_sections, sha256_hex,
    window_id,
)
from .sampling import gumbel, ranked, slot_key, uid, uniforms
from .store import RecipeStore

_SEED_MASK = (1 << 63) - 1


@dataclass(frozen=True)
class PlannerConfig:
    sections: int = 4
    bars_per_section: int = 8
    energy_curve: tuple[float, ...] = (0.45, 0.7, 0.9, 0.6)
    roles: tuple[str, ...] = ROLES
    target_lufs: float = -14.0
    max_gain_db: float = 12.0
    effects: tuple[tuple[str, tuple[tuple[str, float], ...]], ...] = (
        ("vocals", (("reverb_mix", 0.15),)),
        ("other", (("highpass_hz", 120.0),)),
    )
    batch_diversity: float = 1.0
    history_diversity: float = 0.25
    max_tries: int = 64
    max_positions: int = 16
    replacement_similarity_power: float = 4.0
    compat: CompatConfig = DEFAULT_COMPAT
    selection: SelectionConfig = DEFAULT_SELECTION

    def canonical(self) -> dict:
        return {k: (dataclasses.asdict(v) if dataclasses.is_dataclass(v) else v)
                for k, v in dataclasses.asdict(self).items()}


DEFAULT_PLANNER = PlannerConfig()


@dataclass(frozen=True)
class Batch:
    batch_id: str
    recipes: tuple[Recipe, ...]
    ledger: Mapping[str, int]           # song uses so far, including this batch
    unfilled_slots: int

    @property
    def slots(self) -> int:
        return self.recipes[0].batch_slots if self.recipes else 0


@dataclass(frozen=True)
class Replacement:
    section: int
    removed: str                        # stem id
    added: str | None                   # None: no acceptable replacement


@dataclass(frozen=True)
class Patch:
    old_id: str
    new: Recipe
    exclusion_id: str
    rerender: tuple[int, ...]           # sections to re-render with the new placements
    needs_regeneration: tuple[int, ...] # sections with no acceptable replacement
    replacements: tuple[Replacement, ...] = ()

    @property
    def new_id(self) -> str:
        return self.new.recipe_id

    def render_request(self) -> dict:
        """What a renderer needs: the new version and only the sections to redo."""
        return {"recipe_id": self.new_id, "supersedes": self.old_id, "track_id": self.new.root_id,
                "sections": [section_render_spec(self.new.sections[i]) for i in self.rerender],
                "needs_regeneration": list(self.needs_regeneration)}


def section_render_spec(s: Section) -> dict:
    """One section in renderer terms (seconds; field names follow ``remixer.cpu.assemble.StemPick``)."""
    return {"section": s.index, "section_hash": s.section_hash, "start_seconds": s.start_ms / 1000,
            "end_seconds": s.end_ms / 1000, "bpm": s.tempo_bpm, "key": s.key, "seed": s.seed,
            "stems": [{"stem_id": p.stem_id, "source_hash": p.song_id, "stem": p.role,
                       "start_seconds": p.src_start_ms / 1000, "end_seconds": p.src_end_ms / 1000,
                       "offset_seconds": p.dst_start_ms / 1000, "stretch": p.stretch,
                       "tempo_multiplier": p.tempo_multiplier, "semitones": p.shift_semitones,
                       "gain_db": p.gain_db, "effects": [list(e) for e in p.effects]}
                      for p in s.placements]}


def placement_windows(song_id: str, start_ms: int, end_ms: int) -> set[str]:
    return {window_id(song_id, w) for w in range(start_ms // WINDOW_MS, (end_ms - 1) // WINDOW_MS + 1)}


class Planner:
    def __init__(self, catalog: StemCatalog, neighbors: NeighborQuery | None, taste: Callable[[str], float],
                 fatigue: FatigueModel, at_s: float, insights: Sequence[Insight] = (),
                 exclusions: Iterable[Exclusion] = (), config: PlannerConfig = DEFAULT_PLANNER):
        self.config = config
        self.neighbors = neighbors
        self.index = ix = CandidateIndex(catalog.stems(), config.compat)
        self.uids = np.array([uid(s) for s in ix.ids], np.uint64)
        self.order = np.arange(len(ix), dtype=np.int64)
        weights = np.array([candidate_weight(StemCandidate(s.stem_id, s.song_id, float(taste(s.stem_id))),
                                             fatigue, at_s, config.selection) for s in ix.stems], np.float64)
        with np.errstate(divide="ignore"):
            self.log_base = np.log(weights)
        self.insights: dict[str, list[Insight]] = {}
        for i in insights:
            self.insights.setdefault(i.track_id, []).append(i)
        self.exclusions = ExclusionSet(ix, neighbors, exclusions)
        self.effects = dict(config.effects)
        self.non_drum = ix.role != ROLES.index("drums")

    # ------------------------------------------------------------------ helpers

    def _log_div(self, batch_uses: np.ndarray, history: np.ndarray) -> np.ndarray:
        c = self.config
        return -np.log1p(c.batch_diversity * batch_uses + c.history_diversity * history)

    def _blocked(self, stem: StemMeta, start: int, end: int, forbid: set[str]) -> bool:
        if placement_windows(stem.song_id, start, end) & forbid:
            return True
        ins = self.insights.get(stem.song_id)
        return bool(ins) and blocked_by_insight(StemCandidate(stem.stem_id, stem.song_id, 0.0, start, end), ins)

    def _placement(self, stem: StemMeta, start: int, src_len: int, dst_start: int, dst_len: int,
                   stretch: float, mult: float, shift: int) -> Placement:
        c = self.config
        gain = float(np.clip(c.target_lufs - stem.loudness_lufs, -c.max_gain_db, c.max_gain_db))
        return Placement(stem.stem_id, stem.song_id, stem.role, start, start + src_len, dst_start,
                         dst_start + dst_len, round(float(stretch), 6), float(mult), int(shift), round(gain, 1),
                         self.effects.get(stem.role, ()))

    def compatible(self, role: str, target: Target, song_uses: np.ndarray, cap: int):
        """Compatible, allowed, non-zero-weight candidates under the cap: (idx, fit, shift, stretch, mult)."""
        idx, fit, shift, stretch, mult = self.index.query(role, target)
        ok = self.exclusions.allowed[idx] & np.isfinite(self.log_base[idx]) & (song_uses[self.index.song[idx]] < cap)
        return idx[ok], fit[ok], shift[ok], stretch[ok], mult[ok]

    # ------------------------------------------------------------------ planning

    def batch_id(self, n_recipes: int, seed: int) -> str:
        return sha256_hex(canonical_json({"planner": PLANNER_VERSION, "seed": seed, "n": n_recipes,
                                          "config": self.config.canonical()}))[:16]

    def plan_batch(self, n_recipes: int, seed: int, ledger: Mapping[str, int] | None = None) -> Batch:
        ix, c = self.index, self.config
        bid = self.batch_id(n_recipes, seed)
        slots = n_recipes * c.sections * len(c.roles)
        cap = source_cap(slots, c.selection.source_cap_fraction)
        uses = np.zeros(len(ix.songs), np.float64)
        history = np.zeros(len(ix.songs), np.float64)
        for song, n in (ledger or {}).items():
            if song in ix.song_pos:
                history[ix.song_pos[song]] = n
        recipes, unfilled = [], 0
        for r in range(n_recipes):
            recipe, missing = self._plan_recipe(seed, bid, slots, r, uses, history, cap)
            recipes.append(recipe)
            unfilled += missing
        new_ledger = Counter(dict(ledger or {}))
        for i in np.nonzero(uses)[0]:
            new_ledger[ix.songs[i]] += int(uses[i])
        return Batch(bid, tuple(recipes), dict(new_ledger), unfilled)

    def _plan_recipe(self, seed: int, bid: str, slots: int, r: int, uses: np.ndarray, history: np.ndarray,
                     cap: int) -> tuple[Recipe, int]:
        ix, c = self.index, self.config
        rseed = slot_key(seed, bid, r) & _SEED_MASK
        logw = self.log_base + self._log_div(uses, history)[ix.song]
        ok = self.non_drum & self.exclusions.allowed & np.isfinite(logw) & (uses[ix.song] < cap)
        if not ok.any():
            raise ValueError("no usable anchor stem: every stem is banned, disliked or capped")
        cand = np.nonzero(ok)[0]
        anchor = ix.stems[int(cand[np.argmax(logw[cand] + gumbel(slot_key(rseed, "anchor"), self.uids[cand]))])]
        tempo = round(anchor.bpm, 2)
        used_windows: set[str] = set()
        sections, missing, t0 = [], 0, 0
        for k in range(c.sections):
            target = Target(tempo, anchor.key, anchor.meter, c.energy_curve[k % len(c.energy_curve)])
            length = section_length_ms(target, c.bars_per_section)
            placements = []
            for role in c.roles:
                p = self._fill(role, target, t0, length, slot_key(rseed, k, role), uses, history, cap, used_windows)
                if p is None:
                    missing += 1
                else:
                    placements.append(p)
                    uses[ix.song_pos[p.song_id]] += 1
            sec = Section(k, t0, t0 + length, tempo, anchor.key, anchor.meter, target.energy,
                          slot_key(rseed, k) & _SEED_MASK, tuple(placements), needs_regeneration=not placements)
            used_windows |= sec.windows
            sections.append(sec)
            t0 += length
        return Recipe(tuple(sections), rseed, bid, slots), missing

    def _fill(self, role: str, target: Target, dst_start: int, dst_len: int, key: int, uses: np.ndarray,
              history: np.ndarray, cap: int, forbid: set[str]) -> Placement | None:
        ix, c = self.index, self.config
        idx, fit, shift, stretch, mult = self.compatible(role, target, uses, cap)
        if not len(idx):
            return None
        logw = self.log_base[idx] + np.log(fit) + self._log_div(uses[ix.song[idx]], history[ix.song[idx]])
        order = ranked(key, self.uids[idx], logw, idx)
        for j in order[:c.max_tries]:
            stem = ix.stems[int(idx[j])]
            src_len = source_length_ms(dst_len, float(stretch[j]))
            pos = positions(stem, src_len)
            if not pos:
                continue
            first = int(uniforms(key ^ 0x5EED, self.uids[idx[j]:idx[j] + 1])[0] * len(pos))
            for t in range(min(len(pos), c.max_positions)):
                start = pos[(first + t) % len(pos)]
                if not self._blocked(stem, start, start + src_len, forbid):
                    return self._placement(stem, start, src_len, dst_start, dst_len, float(stretch[j]),
                                           float(mult[j]), int(shift[j]))
        return None

    # ------------------------------------------------------------------ ban and replace

    def ban(self, exclusion: Exclusion, store: RecipeStore, lineage: Lineage) -> list[Patch]:
        """Apply an exclusion: future plans avoid it and every affected current recipe is patched."""
        stems = self.exclusions.add(exclusion)
        eid = exclusion_id(exclusion)
        if isinstance(exclusion, SongBan):
            affected = set(lineage.containing(song=exclusion.song_id, heads_only=True))
        else:
            affected = set()
            for s in stems:
                affected |= lineage.containing(stem=s, heads_only=True)
        patches = []
        for rid in sorted(affected):
            old = store.get(rid)
            patch = self.patch(old, eid, store)
            store.supersede(rid, patch.new)
            lineage.add(patch.new)
            patches.append(patch)
        return patches

    def patch(self, old: Recipe, eid: str, store: RecipeStore) -> Patch:
        ix, c = self.index, self.config
        uses = np.zeros(len(ix.songs), np.float64)
        for h in store.heads(old.batch_id):
            for p in h.placements:
                if p.song_id in ix.song_pos:
                    uses[ix.song_pos[p.song_id]] += 1
        cap = source_cap(old.batch_slots, c.selection.source_cap_fraction)
        sections = list(old.sections)
        replacements = []
        for k, sec in enumerate(old.sections):
            bad = [p for p in sec.placements if self.exclusions.blocks(p.stem_id)]
            if not bad:
                continue
            keep = [p for p in sec.placements if not self.exclusions.blocks(p.stem_id)]
            for p in bad:
                if p.song_id in ix.song_pos:
                    uses[ix.song_pos[p.song_id]] -= 1
            forbid = set().union(*(s.windows for i, s in enumerate(sections) if i != k))
            target = Target(sec.tempo_bpm, sec.key, sec.meter, sec.energy)
            needs = False
            for p in bad:
                rep = self.best_replacement(p, target, uses, cap, forbid)
                replacements.append(Replacement(k, p.stem_id, rep.stem_id if rep else None))
                if rep is None:
                    needs = True
                else:
                    keep.append(rep)
                    uses[ix.song_pos[rep.song_id]] += 1
            keep.sort(key=lambda p: ROLES.index(p.role))
            sections[k] = dataclasses.replace(sec, placements=tuple(keep),
                                              needs_regeneration=sec.needs_regeneration or needs)
        new = Recipe(tuple(sections), old.seed, old.batch_id, old.batch_slots, lineage_id=old.root_id,
                     version=old.version + 1, supersedes=old.recipe_id, exclusions=old.exclusions + (eid,),
                     planner_version=old.planner_version)
        changed = changed_sections(old, new)
        return Patch(old.recipe_id, new, eid,
                     rerender=tuple(i for i in changed if not new.sections[i].needs_regeneration),
                     needs_regeneration=tuple(i for i in changed if new.sections[i].needs_regeneration),
                     replacements=tuple(replacements))

    def replacement_scores(self, removed: Placement, target: Target, uses: np.ndarray, cap: int):
        """Candidates for replacing ``removed``: (idx, score, shift, stretch, mult), unsorted."""
        ix, c = self.index, self.config
        idx, fit, shift, stretch, mult = self.compatible(removed.role, target, uses, cap)
        ref = ix.pos.get(removed.stem_id)
        if ref is None or not len(idx):
            return idx, np.zeros(len(idx)), shift, stretch, mult
        sim = (ix.emb[idx] @ ix.emb[ref]).astype(np.float64)
        closeness = np.clip((1.0 + sim) / 2.0, 1e-12, 1.0)
        score = np.exp(c.replacement_similarity_power * np.log(closeness) + np.log(fit) + self.log_base[idx])
        return idx, score, shift, stretch, mult

    def best_replacement(self, removed: Placement, target: Target, uses: np.ndarray, cap: int,
                         forbid: set[str]) -> Placement | None:
        ix = self.index
        idx, score, shift, stretch, mult = self.replacement_scores(removed, target, uses, cap)
        dst_len = removed.dst_end_ms - removed.dst_start_ms
        for j in np.lexsort((idx, -score)):
            stem = ix.stems[int(idx[j])]
            src_len = source_length_ms(dst_len, float(stretch[j]))
            for start in sorted(positions(stem, src_len), key=lambda s: (abs(s - removed.src_start_ms), s)):
                if not self._blocked(stem, start, start + src_len, forbid):
                    return self._placement(stem, start, src_len, removed.dst_start_ms, dst_len, float(stretch[j]),
                                           float(mult[j]), int(shift[j]))
        return None


def plan_and_store(planner: Planner, n_recipes: int, seed: int, store: RecipeStore, lineage: Lineage,
                   ledger: Mapping[str, int] | None = None) -> Batch:
    batch = planner.plan_batch(n_recipes, seed, ledger)
    for r in batch.recipes:
        store.put(r)
        lineage.add(r)
    return batch

"""Fatigue as a decaying state, plus the permanent like/dislike flags (spec section 4).

Entities are opaque ids (by convention ``stem:<id>``, ``source:<id>``, ``track:<id>``).

- ``tired`` ("tired of this") adds fatigue that decays exponentially with ``half_life_s``.
  Increments combine as ``1 - (1 - f)(1 - inc)``, so fatigue stays in [0, 1).
- ``down`` on an entity rated directly sets a permanent ``disliked`` flag (until ``clear``).
  On a generated track it is credited to its stems as negative taste evidence, never as a ban.
- ``up`` adds positive taste evidence and relieves part of the current fatigue.
- Passive signals (early next, exposure) add small, decaying fatigue. They never create ratings.
- A negative on a stem also adds decaying fatigue to its embedding neighbors (one hop).

State is derived: rebuild it by replaying the append-only event log (``replay``).
Nothing here prompts the user; ratings only enter through user-initiated events.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping

from .credit import DEFAULT_CREDIT, CreditConfig, Recipe, loudness_shares
from .propagation import NeighborLookup, neighbor_penalties


@dataclass(frozen=True)
class FatigueConfig:
    half_life_s: float = 3 * 86_400.0
    tired_increment: float = 0.6
    down_fatigue_increment: float = 0.3   # a dislike also makes the sound tiring for a while
    up_relief: float = 0.5                # share of current fatigue removed by a thumbs-up
    early_next_increment: float = 0.10
    mid_next_increment: float = 0.05
    exposure_increment: float = 0.02
    neighbor_k: int = 8
    neighbor_factor: float = 0.3


DEFAULT_FATIGUE = FatigueConfig()


@dataclass
class EntityState:
    fatigue: float = 0.0
    as_of_s: float = 0.0
    disliked: bool = False
    liked: bool = False
    taste_evidence: float = 0.0   # sum of credited +1/-1 shares
    exposures: int = 0


@dataclass
class FatigueModel:
    cfg: FatigueConfig = DEFAULT_FATIGUE
    neighbors: NeighborLookup | None = None
    states: dict[str, EntityState] = field(default_factory=dict)

    def _st(self, entity: str) -> EntityState:
        st = self.states.get(entity)
        if st is None:
            st = self.states[entity] = EntityState()
        return st

    def decayed(self, st: EntityState, at_s: float) -> float:
        dt = max(0.0, at_s - st.as_of_s)
        return st.fatigue * 0.5 ** (dt / self.cfg.half_life_s)

    def fatigue(self, entity: str, at_s: float) -> float:
        st = self.states.get(entity)
        return self.decayed(st, at_s) if st else 0.0

    def is_disliked(self, entity: str) -> bool:
        st = self.states.get(entity)
        return bool(st and st.disliked)

    def taste_evidence(self, entity: str) -> float:
        st = self.states.get(entity)
        return st.taste_evidence if st else 0.0

    def exposures(self, entity: str) -> int:
        st = self.states.get(entity)
        return st.exposures if st else 0

    def add_fatigue(self, entity: str, inc: float, at_s: float) -> None:
        st = self._st(entity)
        cur = self.decayed(st, at_s)
        st.fatigue = 1.0 - (1.0 - cur) * (1.0 - min(max(inc, 0.0), 1.0))
        st.as_of_s = max(st.as_of_s, at_s)

    def _propagate(self, entity: str, inc: float, at_s: float) -> None:
        """Only stems have embedding neighbors; the lookup sees bare stem ids."""
        if not entity.startswith("stem:"):
            return
        for nid, pen in neighbor_penalties(entity[5:], inc, self.neighbors, self.cfg.neighbor_k,
                                           self.cfg.neighbor_factor).items():
            self.add_fatigue(f"stem:{nid}", pen, at_s)

    # ------------------------------------------------------------ user-initiated ratings

    def tired(self, shares: Mapping[str, float], at_s: float) -> None:
        for entity, share in shares.items():
            inc = self.cfg.tired_increment * share
            self.add_fatigue(entity, inc, at_s)
            self._propagate(entity, inc, at_s)

    def down(self, shares: Mapping[str, float], at_s: float, direct: bool) -> None:
        for entity, share in shares.items():
            st = self._st(entity)
            st.taste_evidence -= share
            if direct:
                st.disliked, st.liked = True, False
            inc = self.cfg.down_fatigue_increment * share
            self.add_fatigue(entity, inc, at_s)
            self._propagate(entity, inc, at_s)

    def up(self, shares: Mapping[str, float], at_s: float, direct: bool) -> None:
        for entity, share in shares.items():
            st = self._st(entity)
            st.taste_evidence += share
            if direct:
                st.liked, st.disliked = True, False
            cur = self.decayed(st, at_s)
            st.fatigue = cur * (1.0 - self.cfg.up_relief * share)
            st.as_of_s = max(st.as_of_s, at_s)

    def clear(self, entity: str) -> None:
        st = self.states.get(entity)
        if st:
            st.liked = st.disliked = False

    # ------------------------------------------------------------ passive signals

    def exposure(self, shares: Mapping[str, float], at_s: float) -> None:
        for entity, share in shares.items():
            self._st(entity).exposures += 1
            self.add_fatigue(entity, self.cfg.exposure_increment * share, at_s)

    def passive_next(self, shares: Mapping[str, float], kind: str, at_s: float) -> None:
        inc = {"early_next": self.cfg.early_next_increment, "mid_next": self.cfg.mid_next_increment}.get(kind, 0.0)
        for entity, share in shares.items():
            self.add_fatigue(entity, inc * share, at_s)


RecipeLookup = Callable[[str, str], Recipe | None]


def track_shares(track_id: str, track_version: str, source_kind: str, recipes: RecipeLookup | None,
                 window: tuple[int, int] | None = None, credit: CreditConfig = DEFAULT_CREDIT
                 ) -> tuple[dict[str, float], bool]:
    """Entities a track-level signal lands on, and whether the rating is direct.

    A source track is rated directly (``source:<id>``). A generated track is rated directly as
    ``track:<id>`` and, through credit assignment, across ``stem:<id>`` by loudness share.
    """
    if source_kind == "source":
        return {f"source:{track_id}": 1.0}, True
    recipe = recipes(track_id, track_version) if recipes else None
    if not recipe:
        return {f"track:{track_id}": 1.0}, True
    return {f"stem:{k}": v for k, v in loudness_shares(recipe, window, credit).items()}, False


def replay(events: Iterable, recipes: RecipeLookup | None = None, signals: Iterable = (),
           cfg: FatigueConfig = DEFAULT_FATIGUE, neighbors: NeighborLookup | None = None,
           credit: CreditConfig = DEFAULT_CREDIT) -> FatigueModel:
    """Rebuild the fatigue model from rating events and (optional) T-014 track-level signals.

    Rating events may target a stem directly with ``payload.stem_id``.
    """
    model = FatigueModel(cfg, neighbors)
    items = [(e.wall_time, 0, e) for e in events if e.event_type.startswith("rate_")]
    items += [(s.wall_time, 1, s) for s in signals if s.level == "track"]
    for wall, kind, x in sorted(items, key=lambda t: (t[0], t[1])):
        at_s = wall / 1000.0
        if kind == 1:
            shares, _ = track_shares(x.track_id, x.track_version, x.source_kind, recipes, None, credit)
            model.passive_next(shares, x.kind, at_s)
            continue
        stem = (x.payload or {}).get("stem_id")
        if stem:
            shares, direct = {f"stem:{stem}": 1.0}, True
        else:
            shares, direct = track_shares(x.track_id, x.track_version, x.source_kind, recipes, None, credit)
        if x.event_type == "rate_tired":
            model.tired(shares, at_s)
        elif x.event_type == "rate_down":
            if not direct:
                model.down({f"track:{x.track_id}": 1.0}, at_s, direct=True)
            model.down(shares, at_s, direct)
        elif x.event_type == "rate_up":
            if not direct:
                model.up({f"track:{x.track_id}": 1.0}, at_s, direct=True)
            model.up(shares, at_s, direct)
        elif x.event_type == "rate_clear":
            for entity in (*shares, f"track:{x.track_id}"):
                model.clear(entity)
    return model

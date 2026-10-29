"""Exclusions: what may never appear in a new or patched recipe (decision 0019).

- ``Rest`` is *not* an exclusion: it is the temporary "tired of this" signal and only lowers the
  selection weight through the fatigue model (``rest()`` records it). It never triggers a patch.
- ``SongBan``: every stem of the song, in any recipe planned or patched from now on.
- ``StemTypeBan`` (partial): one role of one song (for example its vocals); its other stems stay usable.
- ``SoundBan``: a neighbourhood in embedding space, every stem within cosine distance ``radius``
  of ``center``. Resolved against the catalog when applied (``NeighborQuery.within`` united with
  an exact scan), so lineage lookups and selection masks agree on the same stem set.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Union

import numpy as np

from remixer.fatigue.state import FatigueModel

from .catalog import NeighborQuery, unit
from .compat import CandidateIndex
from .model import ROLES, canonical_json, sha256_hex


@dataclass(frozen=True)
class Rest:
    entity: str                   # "source:<song_id>" or "stem:<stem_id>" (FatigueModel entity names)


def rest(model: FatigueModel, r: Rest, at_s: float) -> None:
    """Temporary fatigue only; decays on its own and never excludes anything."""
    model.tired({r.entity: 1.0}, at_s)


@dataclass(frozen=True)
class SongBan:
    song_id: str

    def canonical(self) -> dict:
        return {"kind": "song", "song_id": self.song_id}


@dataclass(frozen=True)
class StemTypeBan:
    song_id: str
    role: str

    def __post_init__(self):
        if self.role not in ROLES:
            raise ValueError(f"role {self.role!r} not in {ROLES}")

    def canonical(self) -> dict:
        return {"kind": "stem_type", "song_id": self.song_id, "role": self.role}


@dataclass(frozen=True)
class SoundBan:
    center: tuple[float, ...]
    radius: float                 # cosine distance, 0..2
    label: str = ""

    @classmethod
    def around(cls, vector, radius: float, label: str = "") -> "SoundBan":
        return cls(tuple(round(float(x), 6) for x in unit(vector)), float(radius), label)

    def canonical(self) -> dict:
        return {"kind": "sound", "center": [round(x, 6) for x in self.center], "radius": round(self.radius, 6)}


Exclusion = Union[SongBan, StemTypeBan, SoundBan]


def exclusion_id(e: Exclusion) -> str:
    return sha256_hex(canonical_json(e.canonical()))[:16]


def sound_members(e: SoundBan, index: CandidateIndex, neighbors: NeighborQuery | None) -> frozenset[str]:
    c = unit(e.center)
    exact = np.nonzero(1.0 - index.emb @ c <= e.radius)[0]
    found = {index.ids[i] for i in exact.tolist()}
    if neighbors is not None:
        found |= {s for s in neighbors.within(c, e.radius) if s in index.pos}
    return frozenset(found)


class ExclusionSet:
    """Applied exclusions resolved to a boolean ``allowed`` mask over a ``CandidateIndex``."""

    def __init__(self, index: CandidateIndex, neighbors: NeighborQuery | None = None,
                 exclusions: Iterable[Exclusion] = ()):
        self.index = index
        self.neighbors = neighbors
        self.applied: list[Exclusion] = []
        self.allowed = np.ones(len(index), bool)
        self.banned_stems: set[str] = set()
        for e in exclusions:
            self.add(e)

    def members(self, e: Exclusion) -> frozenset[str]:
        ix = self.index
        if isinstance(e, SongBan):
            s = ix.song_pos.get(e.song_id)
            return frozenset() if s is None else frozenset(ix.ids[i] for i in np.nonzero(ix.song == s)[0])
        if isinstance(e, StemTypeBan):
            s = ix.song_pos.get(e.song_id)
            if s is None:
                return frozenset()
            hit = np.nonzero((ix.song == s) & (ix.role == ROLES.index(e.role)))[0]
            return frozenset(ix.ids[i] for i in hit)
        if isinstance(e, SoundBan):
            return sound_members(e, ix, self.neighbors)
        raise TypeError(f"{type(e).__name__} is not an exclusion (Rest is handled by fatigue)")

    def add(self, e: Exclusion) -> frozenset[str]:
        stems = self.members(e)
        self.applied.append(e)
        self.banned_stems |= stems
        for sid in stems:
            self.allowed[self.index.pos[sid]] = False
        return stems

    def blocks(self, stem_id: str) -> bool:
        return stem_id in self.banned_stems

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(exclusion_id(e) for e in self.applied)

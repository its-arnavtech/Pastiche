"""What the planner needs from the core, as Protocols, plus in-memory fakes used by tests.

The core does not provide these yet. ``opus-cc`` tasks describe them (decision 0011):

- ``StemCatalog``: stem metadata from the catalog's ``stems`` + ``analysis`` + ``embeddings`` rows.
- ``NeighborQuery``: nearest-k and radius queries over stem embeddings (the ``VectorIndex``).
  ``within`` must be exact or a superset of the true ball, because sound-level bans use it to
  find affected recipes.

Embeddings are compared by cosine similarity; ``within`` takes a cosine *distance* radius
(``1 - cosine``), so ``radius = 0.1`` means "cosine similarity at least 0.9".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol, Sequence, runtime_checkable

import numpy as np

from .model import ROLES, parse_key


@dataclass(frozen=True, eq=False)
class StemMeta:
    stem_id: str
    song_id: str
    role: str                    # drums | bass | vocals | other
    bpm: float
    key: str                     # "C# minor"
    meter: int                   # beats per bar
    downbeat_ms: int             # first downbeat; bars follow every meter x 60000 / bpm ms
    loudness_lufs: float
    energy: float                # 0..1
    duration_ms: int
    embedding: np.ndarray        # unit-normalised float32 vector

    def __post_init__(self):
        if self.role not in ROLES:
            raise ValueError(f"role {self.role!r} not in {ROLES}")
        parse_key(self.key)


@runtime_checkable
class StemCatalog(Protocol):
    def stems(self) -> Sequence[StemMeta]:
        """Every stem. Order is irrelevant; the planner sorts by ``stem_id``."""

    def get(self, stem_id: str) -> StemMeta: ...

    def stems_of(self, song_id: str) -> Sequence[StemMeta]: ...


@runtime_checkable
class NeighborQuery(Protocol):
    def nearest(self, vector: np.ndarray, k: int) -> list[tuple[str, float]]:
        """Up to ``k`` (stem_id, cosine similarity), most similar first."""

    def within(self, vector: np.ndarray, radius: float) -> list[str]:
        """Every stem_id whose cosine distance to ``vector`` is <= ``radius`` (exact or superset)."""


def unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(v))
    if n == 0:
        raise ValueError("zero embedding")
    return v / n


class InMemoryCatalog:
    """Fake ``StemCatalog`` + brute-force ``NeighborQuery`` over a stem list."""

    def __init__(self, stems: Iterable[StemMeta]):
        self._stems = list(stems)
        self._by_id = {s.stem_id: s for s in self._stems}
        if len(self._by_id) != len(self._stems):
            raise ValueError("duplicate stem_id")
        self._by_song: dict[str, list[StemMeta]] = {}
        for s in self._stems:
            self._by_song.setdefault(s.song_id, []).append(s)
        self._ids = [s.stem_id for s in self._stems]
        self._matrix = (np.stack([s.embedding for s in self._stems]).astype(np.float32)
                        if self._stems else np.zeros((0, 1), np.float32))

    def stems(self) -> Sequence[StemMeta]:
        return self._stems

    def get(self, stem_id: str) -> StemMeta:
        return self._by_id[stem_id]

    def stems_of(self, song_id: str) -> Sequence[StemMeta]:
        return self._by_song.get(song_id, [])

    def __len__(self) -> int:
        return len(self._stems)

    def nearest(self, vector, k: int) -> list[tuple[str, float]]:
        sims = self._matrix @ unit(vector)
        k = min(k, len(sims))
        top = np.argpartition(-sims, k - 1)[:k] if k else np.array([], dtype=int)
        order = sorted(top.tolist(), key=lambda i: (-float(sims[i]), self._ids[i]))
        return [(self._ids[i], float(sims[i])) for i in order]

    def within(self, vector, radius: float) -> list[str]:
        sims = self._matrix @ unit(vector)
        return sorted(self._ids[i] for i in np.nonzero(1.0 - sims <= radius)[0])

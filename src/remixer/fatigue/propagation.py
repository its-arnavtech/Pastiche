"""Embedding-neighbor propagation: a negative on a stem is felt, more weakly, by similar stems.

The vector index lives in the core; this module only takes a lookup callable
``neighbors(stem_id, k) -> iterable of (neighbor_id, similarity in [0, 1])``.
Propagation is one hop: neighbors of neighbors are not touched.
"""
from __future__ import annotations

from typing import Callable, Iterable

NeighborLookup = Callable[[str, int], Iterable[tuple[str, float]]]


def neighbor_penalties(stem_id: str, penalty: float, neighbors: NeighborLookup | None,
                       k: int = 8, factor: float = 0.3) -> dict[str, float]:
    """``neighbor -> penalty * factor * similarity`` for the ``k`` nearest neighbors (self excluded)."""
    if neighbors is None or penalty <= 0 or factor <= 0:
        return {}
    out: dict[str, float] = {}
    for nid, sim in neighbors(stem_id, k):
        if nid == stem_id:
            continue
        sim = min(1.0, max(0.0, float(sim)))
        if sim > 0:
            out[nid] = max(out.get(nid, 0.0), penalty * factor * sim)
    return out

"""Seeded Gumbel top-k with per-(slot, stem) hashed noise.

Choosing ``argmax(log w_i + G_i)`` with i.i.d. Gumbel noise ``G_i`` samples ``i`` with probability
``w_i / sum(w)``; taking the top k samples without replacement (Gumbel top-k). The noise for stem
``i`` in slot ``s`` is ``splitmix64(slot_key(s) ^ uid(i))`` mapped to a uniform, so it depends only on
the seed, the slot and the stem id: never on catalog order, candidate set or numpy RNG state.
That is what makes a recipe reproducible byte for byte and independent of which other stems exist.
"""
from __future__ import annotations

import hashlib

import numpy as np

_M1 = np.uint64(0xBF58476D1CE4E5B9)
_M2 = np.uint64(0x94D049BB133111EB)
_GOLDEN = np.uint64(0x9E3779B97F4A7C15)


def uid(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "little")


def slot_key(*parts) -> int:
    return uid("|".join(str(p) for p in parts))


def splitmix64(x: np.ndarray) -> np.ndarray:
    with np.errstate(over="ignore"):
        z = x.astype(np.uint64) + _GOLDEN
        z = (z ^ (z >> np.uint64(30))) * _M1
        z = (z ^ (z >> np.uint64(27))) * _M2
        return z ^ (z >> np.uint64(31))


def uniforms(key: int, uids: np.ndarray) -> np.ndarray:
    """Open-interval uniforms in (0, 1), one per uid."""
    h = splitmix64(np.uint64(key) ^ uids.astype(np.uint64))
    return ((h >> np.uint64(11)).astype(np.float64) + 0.5) * (1.0 / 9007199254740992.0)


def gumbel(key: int, uids: np.ndarray) -> np.ndarray:
    return -np.log(-np.log(uniforms(key, uids)))


def ranked(key: int, uids: np.ndarray, log_weights: np.ndarray, tiebreak: np.ndarray) -> np.ndarray:
    """Positions ordered by ``log_weights + Gumbel`` descending (ties by ``tiebreak`` ascending)."""
    perturbed = log_weights + gumbel(key, uids)
    return np.lexsort((tiebreak, -perturbed))

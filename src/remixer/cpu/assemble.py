"""Portable, immutable recipes with seeded tempo/key-compatible stem selection."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json

import numpy as np

from remixer.corpus.generate import KEY_NAMES, STEMS


@dataclass(frozen=True)
class StemPick:
    path: str
    source_hash: str
    stem: str
    start_seconds: float
    end_seconds: float
    source_bpm: float
    semitones: float = 0.0
    gain_db: float = 0.0
    offset_seconds: float = 0.0


@dataclass(frozen=True)
class Recipe:
    stems: tuple[StemPick, ...]
    bpm: float
    key: str
    seed: int = 0
    sample_rate: int = 44100
    target_lufs: float = -16
    effects: tuple[tuple[str, float], ...] = ()
    synthetic: bool = True
    augmented: bool = False
    version: str = "recipe-v1"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> Recipe:
        return cls(**{**value, "stems": tuple(StemPick(**stem) for stem in value["stems"]),
                      "effects": tuple(tuple(effect) for effect in value.get("effects", ()))})

    @property
    def identity(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, allow_nan=False).encode()).hexdigest()


def assemble(rows: list[dict], seed: int = 0, duration: float = 30, bpm: float | None = None,
             key: str | None = None) -> Recipe:
    if not rows or duration <= 0:
        raise ValueError("rows and positive duration required")
    rng = np.random.default_rng(seed)
    reference = rows[int(rng.integers(len(rows)))]
    bpm, key = bpm or reference["bpm"], key or reference["key"]
    tonic = KEY_NAMES.index(key.split()[0])
    minor = key.endswith("minor")
    candidates = [row for row in rows if row["key"].endswith("minor") == minor and .7 <= bpm / row["bpm"] <= 1.4]
    if not candidates:
        raise ValueError("no tempo/key-mode compatible stems")
    picks = []
    for stem in STEMS:
        row = candidates[int(rng.integers(len(candidates)))]
        shift = (tonic - KEY_NAMES.index(row["key"].split()[0]) + 6) % 12 - 6
        source_length = min(row["duration"], duration * bpm / row["bpm"])
        picks.append(StemPick(row["paths"][stem], row["hashes"][stem], stem, 0, source_length,
                              row["bpm"], 0 if stem == "drums" else shift))
    return Recipe(tuple(picks), float(bpm), key, seed, synthetic=any(row.get("synthetic", False) for row in candidates))

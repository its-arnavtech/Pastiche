"""Recipe model: ordered sections of stem placements, canonical bytes, content-addressed ids.

Everything is immutable. A recipe never changes; a ban produces a new version that ``supersedes``
the old one (``patch.py``). Canonical form is compact JSON with sorted keys, floats rounded to
6 decimals and ``-0.0`` folded to ``0.0``, so the same inputs always give the same bytes.

Identity:
- ``Section.section_hash``: sha256 of the section's canonical form. An unchanged section keeps
  its hash across versions, which is how a patch proves what does not need re-rendering.
- ``Recipe.recipe_id``: sha256 of the recipe's canonical form (sections, seed, batch, lineage,
  version, supersedes, applied exclusions).
- ``Recipe.root_id``: the id of version 1; all versions of one generated track share it.
  Playback events use ``track_id = root_id`` and ``track_version = recipe_id``.

Provenance: every placement records its song, stem and the 5-second source windows it reads
(``"<song_id>#<window_index>"``), so the lineage index can answer "what contains X" in one lookup.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Iterable, Mapping

PLANNER_VERSION = "planner-1"
WINDOW_MS = 5000
ROLES = ("drums", "bass", "vocals", "other")
KEY_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def _num(x: float | int) -> float | int:
    if isinstance(x, bool):
        raise TypeError("bool is not a number here")
    if isinstance(x, int):
        return x
    x = float(x)
    if not math.isfinite(x):
        raise ValueError("recipes cannot hold NaN or infinity")
    x = round(x, 6)
    return 0.0 if x == 0 else x


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def window_id(song_id: str, index: int) -> str:
    return f"{song_id}#{index}"


@dataclass(frozen=True)
class Placement:
    """One stem placed in a section: a source range played into a target range."""
    stem_id: str
    song_id: str
    role: str
    src_start_ms: int
    src_end_ms: int
    dst_start_ms: int
    dst_end_ms: int
    stretch: float = 1.0                # time-stretch rate: target_bpm / (source_bpm x tempo_multiplier)
    tempo_multiplier: float = 1.0       # 1, 0.5 (half time) or 2 (double time)
    shift_semitones: int = 0
    gain_db: float = 0.0
    effects: tuple[tuple[str, float], ...] = ()

    def __post_init__(self):
        if self.role not in ROLES:
            raise ValueError(f"role {self.role!r} not in {ROLES}")
        if not (0 <= self.src_start_ms < self.src_end_ms and 0 <= self.dst_start_ms < self.dst_end_ms):
            raise ValueError("placement ranges must be non-empty and non-negative")

    @property
    def windows(self) -> tuple[str, ...]:
        first, last = self.src_start_ms // WINDOW_MS, (self.src_end_ms - 1) // WINDOW_MS
        return tuple(window_id(self.song_id, w) for w in range(first, last + 1))

    def canonical(self) -> dict[str, Any]:
        return {
            "stem_id": self.stem_id, "song_id": self.song_id, "role": self.role,
            "src": [self.src_start_ms, self.src_end_ms], "dst": [self.dst_start_ms, self.dst_end_ms],
            "stretch": _num(self.stretch), "tempo_multiplier": _num(self.tempo_multiplier),
            "shift_semitones": self.shift_semitones, "gain_db": _num(self.gain_db),
            "effects": [[name, _num(v)] for name, v in self.effects],
        }

    @classmethod
    def from_canonical(cls, d: Mapping[str, Any]) -> "Placement":
        return cls(d["stem_id"], d["song_id"], d["role"], d["src"][0], d["src"][1], d["dst"][0], d["dst"][1],
                   d["stretch"], d["tempo_multiplier"], d["shift_semitones"], d["gain_db"],
                   tuple((n, v) for n, v in d["effects"]))


@dataclass(frozen=True)
class Section:
    index: int
    start_ms: int
    end_ms: int
    tempo_bpm: float
    key: str
    meter: int
    energy: float
    seed: int
    placements: tuple[Placement, ...] = ()
    needs_regeneration: bool = False

    def __post_init__(self):
        roles = [p.role for p in self.placements]
        if len(roles) != len(set(roles)):
            raise ValueError(f"section {self.index}: at most one stem per role, got {roles}")
        if [p.role for p in self.placements] != sorted(roles, key=ROLES.index):
            raise ValueError("placements must be in role order")

    def canonical(self) -> dict[str, Any]:
        return {
            "index": self.index, "range": [self.start_ms, self.end_ms], "tempo_bpm": _num(self.tempo_bpm),
            "key": self.key, "meter": self.meter, "energy": _num(self.energy), "seed": self.seed,
            "placements": [p.canonical() for p in self.placements],
            "needs_regeneration": self.needs_regeneration,
        }

    @classmethod
    def from_canonical(cls, d: Mapping[str, Any]) -> "Section":
        return cls(d["index"], d["range"][0], d["range"][1], d["tempo_bpm"], d["key"], d["meter"], d["energy"],
                   d["seed"], tuple(Placement.from_canonical(p) for p in d["placements"]),
                   d["needs_regeneration"])

    @cached_property
    def section_hash(self) -> str:
        return sha256_hex(canonical_json(self.canonical()))

    @property
    def songs(self) -> frozenset[str]:
        return frozenset(p.song_id for p in self.placements)

    @property
    def stems(self) -> frozenset[str]:
        return frozenset(p.stem_id for p in self.placements)

    @property
    def windows(self) -> frozenset[str]:
        return frozenset(w for p in self.placements for w in p.windows)


@dataclass(frozen=True)
class Recipe:
    sections: tuple[Section, ...]
    seed: int
    batch_id: str
    batch_slots: int                     # stem slots in the batch; the per-song cap is relative to this
    lineage_id: str | None = None        # root recipe id; None for version 1
    version: int = 1
    supersedes: str | None = None
    exclusions: tuple[str, ...] = ()     # exclusion ids applied by patches, in order
    planner_version: str = PLANNER_VERSION

    def __post_init__(self):
        if [s.index for s in self.sections] != list(range(len(self.sections))):
            raise ValueError("sections must be indexed 0..n-1 in order")
        if (self.version == 1) != (self.supersedes is None) or (self.version == 1) != (self.lineage_id is None):
            raise ValueError("version 1 has no lineage_id/supersedes; later versions need both")

    def canonical(self) -> dict[str, Any]:
        return {
            "planner_version": self.planner_version, "seed": self.seed,
            "batch": {"id": self.batch_id, "slots": self.batch_slots},
            "lineage_id": self.lineage_id, "version": self.version, "supersedes": self.supersedes,
            "exclusions": list(self.exclusions),
            "sections": [s.canonical() for s in self.sections],
        }

    @cached_property
    def canonical_bytes(self) -> bytes:
        return canonical_json(self.canonical())

    @cached_property
    def recipe_id(self) -> str:
        return sha256_hex(self.canonical_bytes)

    @property
    def root_id(self) -> str:
        return self.lineage_id or self.recipe_id

    @classmethod
    def from_canonical(cls, d: Mapping[str, Any]) -> "Recipe":
        return cls(tuple(Section.from_canonical(s) for s in d["sections"]), d["seed"], d["batch"]["id"],
                   d["batch"]["slots"], d["lineage_id"], d["version"], d["supersedes"], tuple(d["exclusions"]),
                   d["planner_version"])

    @classmethod
    def from_bytes(cls, data: bytes) -> "Recipe":
        return cls.from_canonical(json.loads(data))

    @property
    def placements(self) -> Iterable[Placement]:
        return (p for s in self.sections for p in s.placements)

    @property
    def songs(self) -> frozenset[str]:
        return frozenset(p.song_id for p in self.placements)

    @property
    def stems(self) -> frozenset[str]:
        return frozenset(p.stem_id for p in self.placements)

    @property
    def windows(self) -> frozenset[str]:
        return frozenset(w for p in self.placements for w in p.windows)

    @property
    def section_hashes(self) -> tuple[str, ...]:
        return tuple(s.section_hash for s in self.sections)


def changed_sections(old: Recipe, new: Recipe) -> tuple[int, ...]:
    """Indices whose section hash differs (the sections a renderer must redo)."""
    if len(old.sections) != len(new.sections):
        raise ValueError("versions of one recipe keep their section layout")
    return tuple(i for i, (a, b) in enumerate(zip(old.section_hashes, new.section_hashes)) if a != b)


def key_name(pitch_class: int, minor: bool) -> str:
    return f"{KEY_NAMES[pitch_class % 12]} {'minor' if minor else 'major'}"


def parse_key(name: str) -> tuple[int, bool]:
    tonic, _, mode = name.partition(" ")
    if tonic not in KEY_NAMES or mode not in ("major", "minor"):
        raise ValueError(f"bad key {name!r}; expected like 'C# minor'")
    return KEY_NAMES.index(tonic), mode == "minor"

import hashlib
from collections import Counter

from remixer.fatigue.selection import source_cap
from remixer.fatigue.state import FatigueModel
from remixer.planner import Planner
from remixer.planner.compat import Target, fit, positions
from remixer.planner.library import synthetic_library


def taste(stem_id: str) -> float:
    """Deterministic taste in [0.2, 1.0]."""
    return 0.2 + 0.8 * hashlib.sha256(stem_id.encode()).digest()[0] / 255


_LIBS: dict = {}


def library(n_songs: int, seed: int = 0):
    if (n_songs, seed) not in _LIBS:
        _LIBS[(n_songs, seed)] = synthetic_library(n_songs, seed=seed)
    return _LIBS[(n_songs, seed)]


def make_planner(lib, fatigue=None, **kw):
    return Planner(lib, lib, kw.pop("taste", taste), fatigue or FatigueModel(), kw.pop("at_s", 0.0), **kw)


def check_recipe(planner: Planner, lib, recipe, banned=frozenset(), insights=()):
    """Every per-recipe rule: compatibility, beat grid, roles, window reuse, bans, confirmed insights."""
    seen_windows: dict[str, int] = {}
    for sec in recipe.sections:
        target = Target(sec.tempo_bpm, sec.key, sec.meter, sec.energy)
        roles = [p.role for p in sec.placements]
        assert len(roles) == len(set(roles)), "one stem per role per section"
        for p in sec.placements:
            stem = lib.get(p.stem_id)
            assert p.stem_id not in banned, f"banned stem {p.stem_id} in recipe"
            f = fit(stem, target, planner.config.compat)
            assert f is not None, f"{p.stem_id} incompatible with section {sec.index}"
            assert (p.shift_semitones, p.tempo_multiplier) == (f.shift, f.multiplier)
            assert p.stretch == round(f.stretch, 6)
            assert (p.dst_start_ms, p.dst_end_ms) == (sec.start_ms, sec.end_ms)
            assert p.src_start_ms in positions(stem, p.src_end_ms - p.src_start_ms), "off the downbeat grid"
            for i in insights:
                if i.confirmed and i.track_id == p.song_id:
                    assert not (i.start_ms < p.src_end_ms and p.src_start_ms < i.end_ms), "confirmed insight ignored"
        for w in sec.windows:
            assert seen_windows.setdefault(w, sec.index) == sec.index, f"window {w} reused across sections"


def check_cap(recipes, slots, fraction=0.05):
    counts = Counter(p.song_id for r in recipes for p in r.placements)
    cap = source_cap(slots, fraction)
    assert not counts or max(counts.values()) <= cap, (counts.most_common(3), cap)
    return counts

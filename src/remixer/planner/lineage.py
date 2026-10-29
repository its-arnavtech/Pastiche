"""Lineage index: which recipes contain a song, a stem or a source window, in one lookup each.

Every version of every recipe is indexed (history is immutable); ``heads_only`` filters to the
current version of each lineage, which is what a new ban must patch.
"""
from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from .model import Recipe


@runtime_checkable
class Lineage(Protocol):
    def add(self, recipe: Recipe) -> None: ...

    def containing(self, *, song: str | None = None, stem: str | None = None, window: str | None = None,
                   heads_only: bool = False) -> frozenset[str]: ...

    def head(self, root_id: str) -> str | None: ...

    def is_head(self, recipe_id: str) -> bool: ...


class LineageIndex:
    def __init__(self, recipes: Iterable[Recipe] = ()):
        self.by_song: dict[str, set[str]] = {}
        self.by_stem: dict[str, set[str]] = {}
        self.by_window: dict[str, set[str]] = {}
        self.heads: dict[str, tuple[int, str]] = {}     # root_id -> (version, recipe_id)
        self.root_of: dict[str, str] = {}
        for r in recipes:
            self.add(r)

    def add(self, recipe: Recipe) -> None:
        rid = recipe.recipe_id
        if rid in self.root_of:
            return
        self.root_of[rid] = recipe.root_id
        for p in recipe.placements:
            self.by_song.setdefault(p.song_id, set()).add(rid)
            self.by_stem.setdefault(p.stem_id, set()).add(rid)
            for w in p.windows:
                self.by_window.setdefault(w, set()).add(rid)
        cur = self.heads.get(recipe.root_id)
        if cur is None or recipe.version > cur[0]:
            self.heads[recipe.root_id] = (recipe.version, rid)

    def containing(self, *, song: str | None = None, stem: str | None = None, window: str | None = None,
                   heads_only: bool = False) -> frozenset[str]:
        if sum(x is not None for x in (song, stem, window)) != 1:
            raise ValueError("give exactly one of song, stem, window")
        table, k = ((self.by_song, song) if song is not None else
                    (self.by_stem, stem) if stem is not None else (self.by_window, window))
        hits = table.get(k, ())
        return frozenset(r for r in hits if self.is_head(r)) if heads_only else frozenset(hits)

    def head(self, root_id: str) -> str | None:
        h = self.heads.get(root_id)
        return h[1] if h else None

    def is_head(self, recipe_id: str) -> bool:
        root = self.root_of.get(recipe_id)
        return root is not None and self.heads[root][1] == recipe_id

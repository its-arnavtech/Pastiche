"""Recipe store: immutable versions keyed by content hash, with explicit supersede.

``RecipeStore`` is the interface the core's Catalog should implement (``recipes`` +
``recipe_stems`` tables; task for ``opus-cc``). ``InMemoryRecipeStore`` is the reference fake and
the contract in ``tests/contracts/test_recipe_store.py`` applies to both.

Rules:
- ``put`` stores canonical bytes under ``recipe_id``; putting the same recipe again is a no-op.
  Only version 1 may be ``put``; later versions go through ``supersede``.
- ``supersede(old_id, new)`` requires ``new.supersedes == old_id``, the same root, version + 1 and
  ``old_id`` being the current head. The old version stays readable forever.
- ``get`` returns a recipe equal (byte for byte) to what was stored.
"""
from __future__ import annotations

from typing import Iterator, Protocol, runtime_checkable

from .model import Recipe


class RecipeStoreError(ValueError):
    pass


@runtime_checkable
class RecipeStore(Protocol):
    def put(self, recipe: Recipe) -> str: ...

    def get(self, recipe_id: str) -> Recipe: ...

    def supersede(self, old_id: str, new: Recipe) -> str: ...

    def head(self, root_id: str) -> Recipe: ...

    def versions(self, root_id: str) -> list[Recipe]: ...

    def heads(self, batch_id: str | None = None) -> Iterator[Recipe]: ...


class InMemoryRecipeStore:
    def __init__(self):
        self._bytes: dict[str, bytes] = {}
        self._chain: dict[str, list[str]] = {}       # root_id -> recipe ids by version
        self._batch: dict[str, list[str]] = {}       # batch_id -> root ids

    def __contains__(self, recipe_id: str) -> bool:
        return recipe_id in self._bytes

    def __len__(self) -> int:
        return len(self._bytes)

    def put(self, recipe: Recipe) -> str:
        rid = recipe.recipe_id
        if rid in self._bytes:
            return rid
        if recipe.version != 1:
            raise RecipeStoreError("only version 1 can be put; use supersede for later versions")
        self._bytes[rid] = recipe.canonical_bytes
        self._chain[rid] = [rid]
        self._batch.setdefault(recipe.batch_id, []).append(rid)
        return rid

    def get(self, recipe_id: str) -> Recipe:
        try:
            return Recipe.from_bytes(self._bytes[recipe_id])
        except KeyError:
            raise KeyError(recipe_id) from None

    def supersede(self, old_id: str, new: Recipe) -> str:
        if old_id not in self._bytes:
            raise KeyError(old_id)
        old = self.get(old_id)
        chain = self._chain[old.root_id]
        if chain[-1] != old_id:
            raise RecipeStoreError(f"{old_id[:12]} is not the head of its lineage")
        if new.supersedes != old_id or new.root_id != old.root_id or new.version != old.version + 1:
            raise RecipeStoreError("new version must supersede the head: same root, version + 1")
        rid = new.recipe_id
        self._bytes[rid] = new.canonical_bytes
        chain.append(rid)
        return rid

    def head(self, root_id: str) -> Recipe:
        return self.get(self._chain[root_id][-1])

    def versions(self, root_id: str) -> list[Recipe]:
        return [self.get(r) for r in self._chain[root_id]]

    def heads(self, batch_id: str | None = None) -> Iterator[Recipe]:
        roots = self._batch.get(batch_id, []) if batch_id is not None else list(self._chain)
        for root in roots:
            yield self.head(root)

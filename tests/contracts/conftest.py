"""Adapter contract suite (POC 2 spec sections 6, 8, 9): every profile must pass the same tests.

A profile is one entry in ``PROFILES``: a function ``(scratch_dir, tenant_id) -> Adapters-like`` that
returns an object with ``blobs``, ``catalog``, ``events``, ``jobs``, ``compute`` and
``vector_index(name, dim)``. Opening the same ``tenant_id`` twice must reach the same durable data
(reopen tests rely on it); different ids must never see each other's data (isolation tests).

The local profile has one tenant per data directory. A commercial profile maps ``tenant_id`` onto
its own isolation mechanism (row-level security, per-tenant prefixes) and ignores ``scratch_dir``
apart from cleanup.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Callable

import pytest

from remixer.adapters import Adapters, build
from remixer.config import DEFAULT_PROFILE, Profile, compute_resources


def local_profile(scratch: Path, tenant_id: str) -> Adapters:
    root = scratch / "local-max" / tenant_id
    root.mkdir(parents=True, exist_ok=True)
    raw = copy.deepcopy(DEFAULT_PROFILE)
    return build(Profile(raw=raw, resources=compute_resources({}), data_dir=root))


PROFILES: dict[str, Callable[[Path, str], Adapters]] = {
    "local-max": local_profile,
    # "commercial": commercial_profile,  # opus-cc: register the POC 2 adapters here
}


def close(adapters) -> None:
    for name in ("catalog", "jobs"):
        obj = adapters.__dict__.get(name)  # only what the test actually opened
        if obj is not None and hasattr(obj, "close"):
            obj.close()


@pytest.fixture(params=sorted(PROFILES))
def open_tenant(request, tmp_path):
    """``open_tenant(tenant_id)`` returns a fresh adapter set; each call is a new connection."""
    factory = PROFILES[request.param]
    opened = []

    def _open(tenant_id: str = "tenant-a"):
        a = factory(tmp_path, tenant_id)
        opened.append(a)
        return a

    yield _open
    for a in opened:
        close(a)


@pytest.fixture
def adapters(open_tenant):
    return open_tenant("tenant-a")


_FAKE_RECIPES: dict = {}


def fake_recipe_backend(scratch: Path, tenant_id: str):
    """In-memory reference; 'reopening' a tenant returns the same objects, standing in for durability."""
    from remixer.planner import InMemoryRecipeStore, LineageIndex

    return _FAKE_RECIPES.setdefault((str(scratch), tenant_id), (InMemoryRecipeStore(), LineageIndex()))


_CATALOGS: list = []


def catalog_recipe_backend(scratch: Path, tenant_id: str):
    """SQLite Catalog store (T-024): one catalog per tenant; reopening is a new connection to the same file."""
    from remixer.adapters.planner_catalog import SqliteLineage, SqliteRecipeStore
    from remixer.adapters.sqlite_catalog import SqliteCatalog

    cat = SqliteCatalog(scratch / "catalog-recipes" / tenant_id / "catalog.sqlite")
    _CATALOGS.append(cat)
    return SqliteRecipeStore(cat), SqliteLineage(cat)


# (scratch_dir, tenant_id) -> (RecipeStore, Lineage).
RECIPE_BACKENDS: dict[str, Callable] = {
    "in-memory": fake_recipe_backend,
    "catalog": catalog_recipe_backend,
}


@pytest.fixture(params=sorted(RECIPE_BACKENDS))
def open_recipes(request, tmp_path):
    factory = RECIPE_BACKENDS[request.param]
    yield lambda tenant_id="tenant-a": factory(tmp_path, tenant_id)
    for k in [k for k in _FAKE_RECIPES if k[0] == str(tmp_path)]:
        del _FAKE_RECIPES[k]
    while _CATALOGS:
        _CATALOGS.pop().close()

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

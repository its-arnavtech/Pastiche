"""Filesystem BlobStore: content-addressed, write-to-temp-then-rename (crash safe)."""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from remixer.interfaces import BlobStore


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


class FsBlobStore(BlobStore):
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        ns, _, name = key.rpartition("/")
        digest = name.split(".", 1)[0]
        return self.root / (ns or "blobs") / digest[:2] / name

    def _commit(self, tmp: Path, key: str) -> str:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            tmp.unlink(missing_ok=True)
        else:
            os.replace(tmp, dest)
        return key

    def put(self, data: bytes, namespace: str = "blobs", suffix: str = "") -> str:
        key = f"{namespace}/{sha256_bytes(data)}{suffix}"
        if self.exists(key):
            return key
        tmp = self.root / f".tmp-{os.getpid()}-{id(data)}"
        tmp.write_bytes(data)
        return self._commit(tmp, key)

    def put_file(self, src, namespace: str = "blobs", suffix: str = "") -> str:
        src = Path(src)
        key = f"{namespace}/{sha256_file(src)}{suffix or src.suffix}"
        if self.exists(key):
            return key
        tmp = self.root / f".tmp-{os.getpid()}-{src.name}"
        shutil.copyfile(src, tmp)  # copy, never move: sources may be the user's read-only library
        return self._commit(tmp, key)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def path(self, key: str) -> Path:
        return self._path(key)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

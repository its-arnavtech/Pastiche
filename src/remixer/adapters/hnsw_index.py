"""hnswlib VectorIndex (cosine). Grows capacity automatically; saved atomically."""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Sequence

import numpy as np

from remixer.interfaces import VectorIndex


class HnswIndex(VectorIndex):
    def __init__(self, root: Path, name: str, dim: int, capacity: int = 100_000):
        import hnswlib

        self.file = Path(root) / f"{name}.hnsw"
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.dim = dim
        self._lock = threading.Lock()
        self._idx = hnswlib.Index(space="cosine", dim=dim)
        if self.file.exists():
            self._idx.load_index(str(self.file), allow_replace_deleted=False)
            self._idx.resize_index(max(capacity, self._idx.get_max_elements()))
        else:
            self._idx.init_index(max_elements=capacity, ef_construction=200, M=16)
        self._idx.set_ef(64)

    def add(self, ids: Sequence[int], vectors: np.ndarray) -> None:
        vectors = np.asarray(vectors, dtype=np.float32).reshape(len(ids), self.dim)
        with self._lock:
            need = self._idx.get_current_count() + len(ids)
            if need > self._idx.get_max_elements():
                self._idx.resize_index(max(need, 2 * self._idx.get_max_elements()))
            self._idx.add_items(vectors, np.asarray(ids, dtype=np.int64))

    def search(self, vectors: np.ndarray, k: int = 10) -> tuple[np.ndarray, np.ndarray]:
        vectors = np.asarray(vectors, dtype=np.float32).reshape(-1, self.dim)
        with self._lock:
            k = min(k, self._idx.get_current_count())
            if k == 0:
                empty = np.zeros((len(vectors), 0))
                return empty.astype(np.int64), empty
            labels, dist = self._idx.knn_query(vectors, k=k)
        return labels.astype(np.int64), dist

    def get(self, ids: Sequence[int]) -> np.ndarray:
        """Stored vectors for ``ids`` (unit-normalised in cosine space); KeyError-like RuntimeError if unknown."""
        if not len(ids):
            return np.zeros((0, self.dim), np.float32)
        with self._lock:
            return np.asarray(self._idx.get_items(np.asarray(ids, dtype=np.int64)), dtype=np.float32)

    def save(self) -> None:
        tmp = self.file.with_suffix(".tmp")
        with self._lock:
            self._idx.save_index(str(tmp))
        os.replace(tmp, self.file)

    def __len__(self) -> int:
        return self._idx.get_current_count()

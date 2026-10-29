"""Core interfaces. Core logic depends only on these; adapters implement them per profile.

Local adapters live in `remixer.adapters`; a commercial profile (POC 2) swaps them for cloud ones.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Sequence

import numpy as np


class BlobStore(ABC):
    """Content-addressed blob storage. Keys are hex digests plus optional namespace."""

    @abstractmethod
    def put(self, data: bytes, namespace: str = "blobs", suffix: str = "") -> str: ...

    @abstractmethod
    def put_file(self, src, namespace: str = "blobs", suffix: str = "") -> str: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def path(self, key: str):
        """Local path for memory-mapping, when the backend has one (else None)."""

    @abstractmethod
    def delete(self, key: str) -> None: ...


class Catalog(ABC):
    """Relational catalog: tracks, stems, windows, recipes, renders, ratings, insights."""

    @abstractmethod
    def upsert(self, table: str, row: dict[str, Any], key: Sequence[str]) -> None: ...

    @abstractmethod
    def insert(self, table: str, row: dict[str, Any]) -> int: ...

    @abstractmethod
    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get(self, table: str, **where: Any) -> dict[str, Any] | None: ...


class EventSink(ABC):
    """Append-only event log. Never updates history."""

    @abstractmethod
    def append(self, stream: str, events: Iterable[dict[str, Any]]) -> int: ...

    @abstractmethod
    def read(self, stream: str, where: str | None = None) -> list[dict[str, Any]]: ...


class VectorIndex(ABC):
    @abstractmethod
    def add(self, ids: Sequence[int], vectors: np.ndarray) -> None: ...

    @abstractmethod
    def search(self, vectors: np.ndarray, k: int = 10) -> tuple[np.ndarray, np.ndarray]:
        """Return (ids, distances), each shaped (n, k)."""

    @abstractmethod
    def save(self) -> None: ...

    @abstractmethod
    def __len__(self) -> int: ...


@dataclass
class Job:
    id: int
    kind: str
    key: str
    payload: dict[str, Any]
    attempts: int = 0
    lease_owner: str = ""


class JobQueue(ABC):
    """Durable, at-least-once job queue with leases. Enqueue is idempotent on (kind, key)."""

    @abstractmethod
    def enqueue(self, kind: str, key: str, payload: dict[str, Any] | None = None, priority: int = 0) -> bool:
        """Return True if newly enqueued, False if (kind, key) already exists."""

    @abstractmethod
    def lease(self, kind: str, owner: str, n: int = 1, lease_s: float = 300.0) -> list[Job]: ...

    @abstractmethod
    def ack(self, job_id: int, result: dict[str, Any] | None = None) -> None: ...

    @abstractmethod
    def fail(self, job_id: int, error: str, retry: bool = True) -> None: ...

    @abstractmethod
    def release(self, job_id: int) -> None:
        """Return a leased, unprocessed job to the queue without counting the attempt."""

    @abstractmethod
    def extend(self, job_id: int, lease_s: float = 300.0) -> None: ...

    @abstractmethod
    def counts(self, kind: str | None = None) -> dict[str, int]: ...


@dataclass
class DeviceInfo:
    name: str
    kind: str  # cuda | cpu | npu | igpu
    total_memory: int = 0
    free_memory: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


class ComputeBackend(ABC):
    """Hardware discovery and placement. Machine-specific calls stay behind this."""

    @abstractmethod
    def devices(self) -> list[DeviceInfo]: ...

    @abstractmethod
    def torch_device(self) -> str: ...

    @abstractmethod
    def free_vram(self) -> int: ...

    @abstractmethod
    def cpu_workers(self, lane: str = "cpu") -> int: ...


class LLMClient(ABC):
    @abstractmethod
    def complete(self, prompt: str, system: str | None = None, **kw: Any) -> str: ...

    @abstractmethod
    def available(self) -> bool: ...

    def stream(self, prompt: str, **kw: Any) -> Iterator[str]:
        yield self.complete(prompt, **kw)

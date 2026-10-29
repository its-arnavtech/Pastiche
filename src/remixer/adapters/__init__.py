"""Adapter factory: build the adapters a profile selects. Core code receives these objects."""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from remixer.config import Profile, load_profile
from remixer.interfaces import (BlobStore, Catalog, ComputeBackend, EventSink, JobQueue, LLMClient,
                                VectorIndex)


@dataclass
class Adapters:
    profile: Profile

    def _kind(self, name: str) -> str:
        return self.profile["adapters"][name]

    @cached_property
    def blobs(self) -> BlobStore:
        if self._kind("blob_store") == "fs":
            from remixer.adapters.fs_blobstore import FsBlobStore
            return FsBlobStore(self.profile.path("blobs"))
        raise ValueError(f"unknown blob_store {self._kind('blob_store')}")

    @cached_property
    def catalog(self) -> Catalog:
        if self._kind("catalog") == "sqlite":
            from remixer.adapters.sqlite_catalog import SqliteCatalog
            return SqliteCatalog(self.profile.path("catalog"))
        raise ValueError(f"unknown catalog {self._kind('catalog')}")

    @cached_property
    def events(self) -> EventSink:
        if self._kind("event_sink") == "parquet":
            from remixer.adapters.parquet_events import ParquetEventSink
            return ParquetEventSink(self.profile.path("events"))
        raise ValueError(f"unknown event_sink {self._kind('event_sink')}")

    @cached_property
    def jobs(self) -> JobQueue:
        if self._kind("job_queue") == "sqlite":
            from remixer.adapters.sqlite_queue import SqliteJobQueue
            return SqliteJobQueue(self.profile.path("jobs"))
        raise ValueError(f"unknown job_queue {self._kind('job_queue')}")

    @cached_property
    def compute(self) -> ComputeBackend:
        if self._kind("compute") == "local":
            from remixer.adapters.local_compute import LocalCompute
            return LocalCompute(self.profile.resources)
        raise ValueError(f"unknown compute {self._kind('compute')}")

    @cached_property
    def llm(self) -> LLMClient:
        if self._kind("llm") == "ollama":
            from remixer.adapters.ollama_llm import OllamaClient
            return OllamaClient(**self.profile["llm"])
        raise ValueError(f"unknown llm {self._kind('llm')}")

    def vector_index(self, name: str, dim: int) -> VectorIndex:
        if self._kind("vector_index") == "hnsw":
            from remixer.adapters.hnsw_index import HnswIndex
            return HnswIndex(self.profile.path("vectors"), name, dim)
        raise ValueError(f"unknown vector_index {self._kind('vector_index')}")


def build(profile: Profile | None = None) -> Adapters:
    return Adapters(profile or load_profile())

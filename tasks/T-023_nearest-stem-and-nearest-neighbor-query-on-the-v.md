---
id: T-022
title: Nearest-stem and nearest-neighbor query on the vector index
status: todo
owner: opus-cc
branch: feature/planner-neighbors
lane: none
depends_on: [T-021]
owns_paths: [src/remixer/adapters/, src/remixer/interfaces.py]
claimed_at:
heartbeat_at:
priority: P1
---

## Goal

Provide Catalog-backed adapters for the planner Protocols in src/remixer/planner/catalog.py (see docs/decisions/0013). (1) StemCatalog: stems() -> Sequence[StemMeta]; get(stem_id) -> StemMeta (KeyError if unknown); stems_of(song_id) -> Sequence[StemMeta]. StemMeta(stem_id, song_id, role in drums|bass|vocals|other, bpm, key like 'C# minor', meter, downbeat_ms, loudness_lufs, energy 0..1, duration_ms, embedding unit-normalised float32 ndarray), built from the stems, analysis and embeddings tables. (2) NeighborQuery over the HNSW VectorIndex: nearest(vector, k) -> list[(stem_id, cosine_similarity)] best first, ties by stem_id; within(vector, radius) -> list[stem_id] with cosine distance <= radius, exact or a superset of the true ball (sound-level bans rely on it). Both tenant-scoped. Do not change the planner; it already unions within() with an exact scan.

## Definition of done

Adapters pass a planner run (plan_batch + ban) against a real SqliteCatalog/HnswIndex fixture; contract tests cover nearest ordering, within superset property and tenant isolation.

## Progress and handoff log

- 2026-10-29T04:13:22Z cursor-opus: created

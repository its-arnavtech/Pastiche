# 0013: Recipe planner: what it assumes from the core

- Date: 2026-10-29
- Agent: cursor-opus
- Tasks: T-021 (requests: T-022, T-023, T-024, T-025)

The planner (`src/remixer/planner/`) does not import or edit core, GPU, CPU, DSP or NPU code. Everything
it needs from the core is a `Protocol` in its own module, built and tested against in-memory fakes.
These are the exact signatures assumed; the core should provide adapters with this behavior. The
contract suite checks them: `tests/contracts/test_recipe_store.py`, and `RECIPE_BACKENDS` in
`tests/contracts/conftest.py`.

## StemCatalog (`planner/catalog.py`)

```python
@dataclass(frozen=True)
class StemMeta:
    stem_id: str; song_id: str; role: str            # drums | bass | vocals | other
    bpm: float; key: str                              # "C# minor"
    meter: int; downbeat_ms: int                      # beat grid: bars every meter*60000/bpm ms
    loudness_lufs: float; energy: float               # energy in 0..1
    duration_ms: int; embedding: np.ndarray           # unit-normalised float32

class StemCatalog(Protocol):
    def stems(self) -> Sequence[StemMeta]: ...        # order irrelevant
    def get(self, stem_id: str) -> StemMeta: ...
    def stems_of(self, song_id: str) -> Sequence[StemMeta]: ...
```

The source is the catalog's `stems`, `analysis` and `embeddings` tables plus the vector index (T-022).

## NeighborQuery (`planner/catalog.py`): T-022

```python
class NeighborQuery(Protocol):
    def nearest(self, vector: np.ndarray, k: int) -> list[tuple[str, float]]: ...  # (stem_id, cosine sim), best first
    def within(self, vector: np.ndarray, radius: float) -> list[str]: ...          # cosine distance <= radius
```

`within` must be exact or return a superset of the true ball. Sound-level bans use it to find affected
recipes. The planner unions it with an exact scan of its own columnar index, so an approximate HNSW
`within` that misses neighbors is tolerated, but it is slower.

## RecipeStore (`planner/store.py`): T-023

```python
class RecipeStore(Protocol):
    def put(self, recipe: Recipe) -> str: ...                    # version 1 only; idempotent
    def get(self, recipe_id: str) -> Recipe: ...                 # KeyError if unknown; byte-identical
    def supersede(self, old_id: str, new: Recipe) -> str: ...    # new.supersedes == old_id == head, version+1
    def head(self, root_id: str) -> Recipe: ...
    def versions(self, root_id: str) -> list[Recipe]: ...        # oldest first
    def heads(self, batch_id: str | None = None) -> Iterator[Recipe]: ...
```

It stores `Recipe.canonical_bytes` under `recipe_id` (sha256). Versions are immutable.

## Lineage (`planner/lineage.py`): T-023

```python
class Lineage(Protocol):
    def add(self, recipe: Recipe) -> None: ...                   # idempotent
    def containing(self, *, song=None, stem=None, window=None, heads_only=False) -> frozenset[str]: ...
    def head(self, root_id: str) -> str | None: ...
    def is_head(self, recipe_id: str) -> bool: ...
```

Window ids are `"<song_id>#<index>"` for 5-second source windows. In the catalog, `recipe_stems` (plus a
recipe-window table) indexed by song, stem and window gives the one-lookup answer.

## Deletion: T-024

Deleting a tenant or a track must remove or tombstone every recipe whose provenance contains it,
found through `Lineage.containing(song=...)`, including superseded versions, plus their renders.
Spec POC 2 section 4.

## Renderer hook: T-025

`Patch.render_request()` returns:

```json
{"recipe_id": "...", "supersedes": "...", "track_id": "<root id>",
 "sections": [{"section": 2, "section_hash": "...", "start_seconds": 0.0, "end_seconds": 16.0,
               "bpm": 120.0, "key": "A minor", "seed": 1,
               "stems": [{"stem_id": "...", "source_hash": "<song id>", "stem": "bass",
                          "start_seconds": 4.0, "end_seconds": 20.0, "offset_seconds": 0.0,
                          "stretch": 1.0, "tempo_multiplier": 1.0, "semitones": -2,
                          "gain_db": 1.5, "effects": [["reverb_mix", 0.15]]}]}],
 "needs_regeneration": [3]}
```

The renderer re-renders only the listed sections and splices them into the previous render. It reuses
every other section's audio, keyed by `section_hash`. Stem field names follow
`remixer.cpu.assemble.StemPick`.

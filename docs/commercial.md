# Commercial profile (POC 2): the paper design

Status: **design only.** No thin slice was built, nothing was deployed, nothing cost money. The spec is
`docs/specs/stemdna-poc2-commercial.md`; the numbers are in `docs/unit-economics.md`, the licenses in `docs/licenses.md`, the legal
options in `docs/legal-paths.md`, the hosting path in `docs/deployment.md`.

## What the commercial profile is

The same product as POC 1, served to many users from shared infrastructure at a cost per user low enough for a free tier. The core
(recipes, planner, fatigue, event interpretation, heatmap, insight layer, section-cached rendering) does not change. Only the
adapters behind the interfaces and `profile.yaml` change.

| Interface (`src/remixer/interfaces.py`) | local-max (built, tested) | commercial (target, not built) |
|---|---|---|
| `BlobStore` | filesystem, content-addressed | S3-compatible object store, per-tenant prefix |
| `Catalog` | SQLite (WAL) | Postgres with row-level security per tenant |
| `EventSink` | Parquet files, read with DuckDB | Parquet batches in object storage, batch analytics |
| `VectorIndex` | hnswlib | `pgvector` |
| `JobQueue` | SQLite lease table | a real queue (leases, retries, dead letter, priorities) |
| `ComputeBackend` | local CUDA, CPU pool, OpenVINO NPU | elastic CPU pool, spot GPU for batch only |
| `LLMClient` | Ollama (`qwen3:4b`) | hosted or self-served model, rate-limited per tenant |

The planner's own Protocols are part of the same seam: `StemCatalog` and `NeighborQuery` (`planner/catalog.py`), `RecipeStore` and
`Lineage` (`planner/store.py`, `planner/lineage.py`). Their SQLite implementations are in `adapters/planner_catalog.py`, with
`delete_track` and `delete_tenant`.

## Cost design in one paragraph

Separate once, cache forever (content-addressed stems); no GPU on the request path; assemble in the browser or on cheap CPUs; batch
GPU work on spot capacity (every stage is checkpointed and resumable); cache embeddings by content hash and model version; free tier
uses a shared cleared catalog and CPU-only remixing; paid tier adds generation and a priority queue. Measured: 83 GPU-seconds and
2.5 GB of WAV stems per audio hour (`docs/unit-economics.md`).

## Multi-tenancy

Every row and blob path carries a tenant id; taste, fatigue, recipes, ratings and events are per tenant; row-level security in the
catalog; quotas at the queue; deleting a track or a tenant removes derived artifacts. What exists today:

- Tenant isolation is tested for the local profile (one data directory per tenant): `tests/contracts/test_tenant_isolation.py`.
- Deletion is implemented and tested: `delete_track`, `delete_tenant` (`tests/contracts/test_planner_catalog.py`), including recipes,
  renders, lineage rows, stems, embeddings and events.
- Origin separation inside one tenant (synthetic vs real) is enforced in `src/remixer/product.py` and tested in
  `tests/test_real_use_path.py`.
- Quotas and cost events do not exist.

## Is the adapter boundary the only thing a commercial profile must replace?

**Mostly yes. Four exceptions, found by searching core code for storage and platform assumptions.**

What holds. The contract suite (`tests/contracts/`: blob store, catalog, compute, determinism, event sink, insight job, job queue,
planner catalog, recipe store, tenant isolation, vector index) is written against `Adapters`-like objects, and the local profile is
registered as the only entry in `PROFILES` (`tests/contracts/conftest.py`). A second profile is one more entry. Windows-specific calls
are confined to `adapters/local_compute.py`, `adapters/cpu_topology.py`, `telemetry/` and `bench/` (the benchmark harness); `planner/scale.py`
is a local benchmark. Rendering is deterministic (the same recipe renders to the same bytes, `tests/contracts/test_determinism.py`
and the demo), which is what the "identical renders under both profiles" criterion needs.

What leaks (each is a task, none is a rewrite):

1. **Stems, embeddings and checkpoints are local files, not `BlobStore` objects.** `stems.blob_key` is a path relative to
   `profile.data_dir`; `gpu/separate.py`, `gpu/embed.py`, `gpu/taste.py`, `product.py` and `server/app.py` join it to the data directory
   and open it. A commercial profile would need the lanes to fetch and publish stems through `BlobStore`. Effort: about 2 days.
2. **`server/app.py` asks SQLite for its table list** (`sqlite_master`, line 76). Replace with a catalog capability check. Effort: under an hour.
3. **`adapters/planner_catalog.py` reaches into the catalog's private connection and lock** (`catalog._con`, `catalog._lock`) for its
   transactions. That is acceptable only while it is the SQLite flavour of the planner adapter; a Postgres flavour is part of the
   commercial adapter set, and the contract tests for it exist. The `Catalog` interface does not expose transactions, so a
   commercial version needs either that interface extended or the planner adapters implemented per backend. Effort: about 2 days.
4. **Raw SQL strings against `Catalog.query`** appear in core (`product.py`, `insight_job.py`, `demo.py`, the lanes). They are plain
   `SELECT`s and port to Postgres, but they pin table and column names into the core. Acceptable; record it so schema changes go
   through the contract tests.

Also outside the seven interfaces, and so part of the same boundary: the lane processes read `config/resources.yaml` and
`profile.yaml` for core and GPU budgets (`ComputeBackend` territory), and the nightly job is scheduled by the host (`docs/NEEDS_USER.md`).

**Conclusion.** The interfaces plus the contract tests are the boundary the commercial profile replaces, with the stem-storage leak
(1) as the one real piece of work in the core's lanes.

## Not built, per instruction

The thin slice in the POC 2 spec (local Postgres, a MinIO-style store, a real queue, two simulated tenants, identical renders across
profiles) was out of scope for this wrap-up. The prerequisites that are done: interfaces and contract suite, deletion, determinism,
isolation tests for the local profile.

## Open decisions for the owner

1. The legal path (`docs/legal-paths.md`). It decides whether stems are ever stored server-side.
2. The GPL pieces (`docs/licenses.md`): client-side or distributed rendering needs a different time-stretch library or a license.
3. Whether a hosted LLM or a self-hosted small model is acceptable for insights (and which: `docs/KNOWN_LIMITATIONS.md`).

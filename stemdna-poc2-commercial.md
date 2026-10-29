# StemDNA POC 2: Commercial Design (Claude Code Build Spec)

This is the second proof of concept of StemDNA: the same product as POC 1, designed to run as a public, multi-user, budget-constrained service. Current budget is $0, so this POC is a **design plus a thin local slice**. Nothing gets deployed and nothing costs money.

POC 1 (`stemdna-poc1-local-max.md`) is built first and is the priority. POC 2 reuses its core (pipeline stages, recipes, feedback model, event log, fatigue, skip analytics) unchanged. This file defines only what differs: the adapters, cost strategy, multi-tenancy, licensing, and the deployment path. Do not reference or reuse any other existing project. This is standalone.

---

## 1. Goal and constraints

- Serve many users from shared infrastructure at a cost per user low enough to sustain a free tier.
- The core must not change between profiles. Only adapters and configuration differ (`profile.yaml` selects `local-max` or `commercial`).
- Budget is $0 now. Every design choice below should be testable locally for free and deployable later on free or cheap tiers.

## 2. Adapter mapping

| Interface | local-max (POC 1) | commercial (target) |
|---|---|---|
| `BlobStore` | local filesystem | S3-compatible object storage, content-addressed, per-tenant prefix |
| `Catalog` | SQLite | Postgres with tenant row-level isolation |
| `EventSink` | Parquet files + DuckDB | append-only batches to object storage as Parquet, queried in batch |
| `VectorIndex` | FAISS / hnswlib | pgvector (or a managed vector service if needed) |
| `JobQueue` | SQLite job table + multiprocessing | a real queue with retries, dead-letter, priorities |
| `ComputeBackend` | local GPU and cores | elastic workers: CPU pool for DSP, spot/preemptible GPU for batch jobs |
| `LLMClient` | local Ollama | hosted API or self-served small model, rate-limited per tenant |

## 3. Cost strategy (the main design problem)

- **Separate once, cache forever.** Stem separation is the largest GPU cost. Store stems content-addressed, so identical audio is separated once. Sharing across tenants is allowed only where licensing permits (see section 5).
- **No GPU on the request path.** Assembly (stretch, shift, mix) is cheap DSP. Do it client-side in the browser or on cheap CPU workers. Reserve GPUs for batch jobs.
- **Batch GPU work off-peak** on spot/preemptible capacity. Jobs must be checkpointed and resumable (already required by POC 1).
- **Smaller, quantized models.** Cache embeddings by content hash and model version. Never recompute.
- **Tiered features.** Free tier: precomputed or user-owned stems, CPU-only remixing. Paid tier: GPU generation and priority queue.
- **Event log as cheap storage.** Append-only Parquet in object storage, with nightly batch analytics instead of always-on clusters.
- **Per-tenant cost accounting from day one.** Record compute seconds, GPU seconds, storage GB, and egress as events, so unit economics are measurable.

Deliver a worksheet `docs/unit-economics.md` with estimated cost per processed hour of audio and per active user per month, with every assumption stated and marked as an estimate to be replaced by measured numbers from POC 1's telemetry.

## 4. Multi-tenancy

- Every table row and blob path carries `tenant_id`. Taste models, fatigue state, recipes, ratings and events are per tenant.
- Row-level security in the catalog; no cross-tenant queries in application code.
- Per-tenant quotas (storage, jobs per day, GPU seconds) enforced at the queue.
- Deletion: deleting a tenant or a track removes derived artifacts (stems, embeddings, recipes, renders) and tombstones events. Design this early; retrofitting it is painful.

## 5. Licensing and legal (gating issue)

- Separating and recombining commercial copyrighted recordings on a server and distributing the results is a serious legal problem. Do not design a commercial product around ingesting arbitrary copyrighted music.
- Evaluate and document three viable paths: (a) on-device processing of the user's own files, with nothing copyrighted uploaded or stored server-side; (b) licensed, royalty-free or Creative Commons catalogs with verified terms; (c) a direct licensing agreement.
- Record the license of every model and dependency in `docs/licenses.md`. Some popular music-generation weights are non-commercial only, and some carry revenue limits. Do not ship a model whose license forbids the intended use.
- This is not legal advice. Flag the document for review by someone qualified before any public launch.

## 6. Thin slice (free, runs locally)

Prove the adapter boundary without spending anything:

- Run the core with the `commercial` profile against free local stand-ins: Postgres (local), an S3-compatible local object store (such as MinIO), and a real queue running locally.
- Run two simulated tenants and verify isolation (a test must fail if tenant A can read tenant B's data).
- Run the same sample library through both profiles and confirm identical recipes and identical renders for the same seed.
- Measure and record cost-relevant numbers (GPU seconds and storage per track) from POC 1 telemetry and feed them into `unit-economics.md`.

## 7. Free-tier deployment sketch (document only)

Write `docs/deployment.md` describing a $0 path: static front end and API on free hosting tiers, free-tier Postgres and object storage, batch GPU jobs run on the owner's own machine (or donated or free GPU credits), and the staged upgrade path as usage grows with rough unit costs. Include what would break first at each scale step.

## 8. Phases

1. Confirm POC 1's interfaces are clean (no machine-specific code in core). Fix leaks.
2. Define commercial adapters as stubs with contract tests that both profiles must pass.
3. Build the thin slice (section 6) with tenant isolation tests.
4. Write `docs/unit-economics.md`, `docs/licenses.md`, `docs/deployment.md`, and `docs/legal-paths.md`.
5. Review with the owner; decide on the licensing path before any deployment work.

## 9. Acceptance criteria

- The same core code passes the same contract tests under both profiles.
- Tenant isolation tests pass; deletion removes all derived artifacts for a tenant.
- Identical recipe and seed produce an identical render under both profiles.
- The four docs exist, state their assumptions, and cite measured numbers where POC 1 provides them.
- Total spend: $0.

## 10. Working rules for Claude Code

- Do not start until POC 1 phases 1 to 3 are done.
- Do not change core behavior to fit commercial needs; change adapters or add configuration.
- Never add a dependency without recording its license.
- Ask before any step that would cost money or require an account with payment details.
- Commit in small steps, keep `NOTES.md` current, and do not add features beyond this spec without asking.

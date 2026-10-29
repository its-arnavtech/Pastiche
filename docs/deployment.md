# Deployment (POC 2, paper only): a $0 path and the upgrade steps

Nothing here has been built, deployed or paid for. It describes how the commercial profile (`docs/commercial.md`) could go live
at $0 and what to upgrade, in order, as usage grows. Prices and free-tier limits are **recalled, not checked**: free tiers change,
so confirm each one on the vendor's page before relying on it (`docs/unit-economics.md` lists the same caveat). Pick the legal path
first (`docs/legal-paths.md`); it decides what may be stored at all.

## Principle

Keep GPUs off the request path. The browser (or the user's own machine) does the cheap DSP; the owner's laptop does the batch
GPU work, as it already does. Servers hold small things: recipes, ratings, events, taste vectors, insights, and stems only when
the legal path allows.

## Stage 0: $0 (friends, a handful of users)

| Piece | Free option | Notes |
|---|---|---|
| Static front end (`web/`) and API | a free static host plus a free serverless or container tier | Choose a tier whose terms allow the use. Some "hobby" tiers forbid commercial use |
| Catalog (Postgres) | a free-tier managed Postgres with a few hundred MB | Holds tracks, recipes, ratings, tenant rows. Row-level security per tenant |
| Object storage (stems, renders) | a free tier of an S3-compatible store (about 10 GB) | Holds a small cleared catalog only (path b); about 1.4 GB per audio hour as FLAC, so 10 GB is roughly 7 hours |
| Events | Parquet files in the same object store, or a table | Nightly batch analytics; 0.11 MB per user per month |
| Vector index | `pgvector` in the same Postgres, or in-process hnswlib rebuilt at start | Hundreds of thousands of vectors fit in memory (2.2 KB each) |
| Job queue | a Postgres table with leases (the SQLite queue's design) | No new service |
| GPU batch work | **the owner's laptop** (the stable preset), pulling jobs from the queue and pushing stems and vectors | Zero cost; throughput about 58 audio-s/s, so a 10,000-track catalog takes about 13 GPU-hours (`docs/unit-economics.md`) |
| LLM insights | a small hosted model's free allowance, or Ollama on the laptop | One short pass per user per night |
| Rendering | in the browser, or on the free serverless CPU | Browser is cheaper and private; the renderer must then be client-side (see the Pedalboard and Rubber Band license flag in `docs/licenses.md`) |
| Auth | the host's free auth, or a magic-link flow | Accounts are the first thing that costs time, not money |

**Operator tasks at this stage:** run the laptop worker when jobs are queued; keep it on AC with clear vents (it shut down twice
uncapped, `docs/PEAK_REPORT.md`); take a backup of the catalog.

**What breaks first:** the laptop. One GPU, thermally limited, shared with the owner's work, and nothing runs while it sleeps.
Second: free Postgres storage (a few hundred MB) once recipes and events accumulate. Third: free-tier cold starts and request
timeouts on the API.

## Stage 1: about $10-50 per month (hundreds of users)

- A small paid Postgres and an object store with no egress fee. Stems as FLAC or lossy cost $2-30 per month for 583 audio hours
  (`docs/unit-economics.md`, section 4).
- Rent spot GPU time for batch separation instead of the laptop: 13.4 GPU-hours for a 10,000-track catalog is $3-13 once.
  Jobs are already checkpointed, resumable and idempotent (`docs/ACCEPTANCE.md`), which is what spot capacity needs. Note the
  GeForce driver terms in `docs/licenses.md`.
- A real queue (the contract tests in `tests/contracts/` define what it must do: leases, retries, exactly-one lease).
- Per-tenant cost events (compute seconds, GPU seconds, storage, egress) start being written.

**What breaks first:** storage cost if stems stay lossless, and the single-writer assumptions in the Parquet event sink (it writes
one part file per POST; it needs compaction).

## Stage 2: about $100-500 per month (thousands of users)

- Autoscaled CPU workers for planning and server-side renders ($0.00023 per recipe at the assumed core price).
- Postgres with replicas or a larger instance; `pgvector` or a managed vector store once per-tenant search gets heavy.
- Hosted LLM with per-tenant rate limits, or a self-hosted Apache-2.0 model on a GPU shared with batch work (serialize or swap;
  Demucs and a 7-8B model do not fit in 8 GB together).
- Quotas enforced at the queue (storage, jobs per day, GPU seconds) and billing events if there is a paid tier.

**What breaks first:** the nightly insight batch (one model pass per user), and anything that scans all events instead of a
partition.

## Stage 3: beyond

Split the catalog into per-region stores, move stems to a CDN, and revisit the licensing path (direct licensing, path c) because
the legal exposure, not the compute, is what grows with scale.

## Upgrade checklist

1. Choose the legal path and get it reviewed.
2. Build the thin slice from the POC 2 spec: commercial adapters behind the same contract tests, two tenants, an isolation test
   that fails if tenant A reads tenant B, identical recipes and renders for the same seed under both profiles. None of this exists
   yet (the commercial profile is not registered in `tests/contracts/conftest.py`).
3. Close the boundary leaks in `docs/commercial.md` (stems as local paths, one SQLite-specific query in the server).
4. Replace or license the GPL pieces.
5. Add per-tenant cost events, then re-do `docs/unit-economics.md` with measured numbers.

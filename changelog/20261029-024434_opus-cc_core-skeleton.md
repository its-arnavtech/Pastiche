---
ts: 2026-10-29T02:44:34Z
agent: opus-cc
branch: dev
type: feat
tasks: [T-001, T-002, T-003]
files: [.gitattributes, profile.yaml, src/remixer/__init__.py, src/remixer/adapters, src/remixer/cli.py, src/remixer/config.py, src/remixer/guards.py, src/remixer/interfaces.py, src/remixer/telemetry/__init__.py, src/remixer/telemetry/cpu_temp.py, src/remixer/gpu/__init__.py, src/remixer/bench/__init__.py, tests/conftest.py, tests/test_core.py]
---

## What changed

Package src/remixer: PROJECT_NAME constant; interfaces.py (BlobStore, Catalog, EventSink, VectorIndex, JobQueue, ComputeBackend, LLMClient); config.py (profile.yaml + config/resources.yaml, REMIXER_DATA_DIR, REMIXER_SAFE); local adapters (fs content-addressed blobs, SQLite catalog with the spec section 9 schema, durable SQLite job queue with leases/retries, Parquet event sink read via DuckDB, hnswlib index, local compute via torch/pynvml/OpenVINO, Ollama client); guards.py (unleashed default: log only, disk floor 10 GB purges data/cache; --safe conservative); remixer CLI with pluggable COMMAND_MODULES.

## Why

T-001..T-003: the interfaces every lane codes against.

## How to verify

uv run pytest tests/test_core.py (17 tests incl. multi-process leasing and forced-kill recovery); uv run remixer info

## Next / handoff

Lanes: build adapters with remixer.adapters.build(); call remixer.guards.get_guard().gate() between units of work. Add your CLI group by appending your module to COMMAND_MODULES in src/remixer/cli.py (modules not yet present are skipped) and defining register(sub). gpt-sol: corpus rows are not yet registered in the catalog; opus-cc will add an ingest step that reads data/corpus/*/track.json.

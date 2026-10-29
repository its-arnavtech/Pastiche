# 0010: Adapter contract suite

- Date: 2026-10-29
- Agent: cursor-opus
- Tasks: T-020

## Decision

1. `tests/contracts/` holds one suite that every profile runs. A profile is one entry in
   `PROFILES` (`tests/contracts/conftest.py`): `(scratch_dir, tenant_id) -> adapters`. The local
   profile builds `remixer.adapters.build(Profile(data_dir=<scratch>/<tenant_id>))`, so the real
   factory is under test. Opening the same tenant twice must reach the same durable data.
2. Tenant isolation for the single-tenant local profile is one data directory per tenant. The
   commercial profile maps `tenant_id` onto row-level security and per-tenant prefixes. The isolation
   check is itself tested: two handles on the same tenant must make it fail.
3. EventSink read order is not part of the contract. Consumers sort with `sort_events`, which
   breaks equal-`wall_time` ties with `client_info.seq`. The web client and the simulator both stamp
   `seq`. A probe without `seq` showed shuffled storage changing the heatmap, so this is load-bearing.
4. Events are stored flat with `Event.to_row()` (nested fields as JSON text, same layout as the
   T-014 Parquet scale path) and read with `Event.from_row()`, which ignores extra storage columns.
5. Determinism means the analytics and fatigue pipeline produces identical heatmap rows, candidates,
   insights, signals, fatigue values and seeded selection batch whether it reads events
   directly, from one append, or from shuffled 97-row appends into another tenant.
6. Not covered yet: `LLMClient` (needs a running Ollama), `ComputeBackend.torch_device` (needs torch),
   and tenant deletion (the interfaces have no delete-tenant operation yet; spec section 4).

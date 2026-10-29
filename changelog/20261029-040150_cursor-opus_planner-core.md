---
ts: 2026-10-29T04:01:50Z
agent: cursor-opus
branch: feature/recipe-planner
type: feat
tasks: [T-022]
files: [src/remixer/planner/, tests/planner/, pyproject.toml, uv.lock]
---

## What changed

Branch feature/recipe-planner was created from feature/skip-analytics because PR #1 (T-014/15/16/21) was not merged into dev yet (since merged; branch rebased onto dev). remixer.planner: immutable sectioned Recipe/Section/Placement with canonical JSON bytes, sha256 recipe_id and section_hash, root_id/version/supersedes, provenance (songs, stems, 5 s source windows); StemCatalog and NeighborQuery Protocols with InMemoryCatalog fake; compatibility (Camelot key distance with pitch shift, tempo stretch within 8 percent incl. half/double time, meter + downbeat-grid source starts, energy tolerance, one stem per role) as a scalar reference plus a vectorized CandidateIndex; hashed Gumbel-max sampling (order-independent, reproducible); planning reuses fatigue.selection.candidate_weight, blocked_by_insight and source_cap; diversity term with a cross-batch ledger; no source-window reuse across sections; LineageIndex and InMemoryRecipeStore; exclusion kinds (Rest, SongBan, StemTypeBan, SoundBan); synthetic stem library. Dependency: new optional group planner = numpy>=2.4.6 (numpy already a core dependency).

## Why

T-022 brief sections 1, 2 and 4.

## How to verify

uv run pytest tests/planner (38 passed): byte-identical recipes for the same seed and for a reversed catalog; vectorized compatibility equals the scalar reference; cap, roles, windows, beat grid hold; unconfirmed insights (pending, no, unsure) leave bytes unchanged; bans never appear; coverage grows across batches.

## Next / handoff

Ban-and-replace tests (minimal sections, brute-force replacement), scale run, recipe-store/lineage contracts, opus-cc interface tasks.

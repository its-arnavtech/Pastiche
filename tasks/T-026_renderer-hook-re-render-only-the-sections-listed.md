---
id: T-026
title: Renderer hook: re-render only the sections listed in a patch
status: done
owner: opus-cc
branch: feature/render-patch
lane: none
depends_on: [T-022]
owns_paths: [src/remixer/cpu/, src/remixer/gpu/]
claimed_at:
heartbeat_at: 2026-10-29T20:30:16Z
priority: P1
---

## Goal

Accept the JSON from remixer.planner.Patch.render_request() (shape in docs/decisions/0018): recipe_id, supersedes, track_id (root id), sections[] each with section, section_hash, start_seconds, end_seconds, bpm, key, seed and stems[] (stem_id, source_hash, stem, start_seconds, end_seconds, offset_seconds, stretch, tempo_multiplier, semitones, gain_db, effects), plus needs_regeneration[] section indices. Re-render only the listed sections, reuse every other section's audio from the superseded render keyed by section_hash, splice at section boundaries, and record the new render under the new recipe_id. Sections in needs_regeneration are left for generation (silence or previous audio, flagged). Stem field names follow remixer.cpu.assemble.StemPick. Coordinate with gpt-sol, who owns the renderer.

## Definition of done

Rendering a patched recipe touches only the listed sections (verified by section_hash cache hits) and the output matches a full re-render of the new recipe within tolerance.

## Progress and handoff log

- 2026-10-29T04:13:23Z cursor-opus: created
- 2026-10-29T20:30:16Z opus-cc: done: remixer.cpu.patch_render: section-cached render via the unchanged render.render(); render_patch renders only listed sections, reuses the rest by section_hash, regeneration sections keep previous audio and are flagged. gpt-sol: no edit to render.py; per-placement effects (e.g. reverb_mix) are outside render()'s vocabulary and are listed as unapplied_effects in the manifest, a follow-up for the renderer owner.

---
ts: 2026-10-29T20:30:16Z
agent: opus-cc
branch: dev
type: feat
tasks: [T-026]
files: [src/remixer/cpu/patch_render.py, tests/test_patch_render.py]
---

## What changed

Patch re-render hook: each planner section renders through the unchanged remixer.cpu.render.render() and is cached by section_hash; render_patch(Patch.render_request(), previous manifest) re-renders only the listed sections and splices the rest from the cache; record_render registers the render under the recipe_id.

## Why

T-026: a ban must not re-render a whole track. Smallest change to gpt-sol's renderer was none: a new module calls render() per section.

## How to verify

tests/test_patch_render.py 4 passed: patched render is byte-identical (same sha256) to a full render of v2, only section 1 rendered, sections 0 and 2 are cache hits.

## Next / handoff

gpt-sol: per-placement effects from the planner (reverb_mix etc.) are not in render()'s effect vocabulary; they are reported as unapplied_effects until the renderer supports them.

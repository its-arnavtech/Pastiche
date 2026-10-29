"""Section-cached rendering of planner recipes and patch re-renders (T-026, decision 0018).

Each planner section renders on its own through ``remixer.cpu.render.render`` (unchanged) and is cached
under its ``section_hash``. A full render renders or reuses every section and splices them at their
section boundaries. A patch (``Patch.render_request()``) renders only the sections it lists; every other
section must come from the cache, keyed by the hash it kept from the previous version. Because sections
are rendered independently and deterministically, a patched render equals a full render of the new
version. Sections in ``needs_regeneration`` keep the previous version's audio when it is cached (else
silence) and are flagged in the manifest.

The manifest (``<output>.json``) stores every section's render spec, so the next patch builds on it.
Placement effects outside the renderer's vocabulary (it supports mix-level gain/filters/delay only) are
listed under ``unapplied_effects`` rather than silently dropped.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import soundfile as sf

from remixer.corpus.generate import atomic_json, atomic_replace, file_hash
from .assemble import Recipe as RenderRecipe, StemPick
from .render import VERSION as RENDER_VERSION, render

VERSION = "section-render-v1"
Resolver = Callable[[str], Path]       # stem_id -> stem audio file


def _cache_file(cache_dir: Path, section_hash: str, sample_rate: int) -> Path:
    return cache_dir / f"{section_hash}-{sample_rate}-{RENDER_VERSION}.wav"


def _render_section(spec: dict, resolve: Resolver, cache_dir: Path, sample_rate: int,
                    unapplied: list) -> Path:
    out = _cache_file(cache_dir, spec["section_hash"], sample_rate)
    length = round((spec["end_seconds"] - spec["start_seconds"]) * sample_rate)
    picks = []
    for st in spec["stems"]:
        path = Path(resolve(st["stem_id"]))
        picks.append(StemPick(str(path), file_hash(path), st["stem"], st["start_seconds"], st["end_seconds"],
                              source_bpm=spec["bpm"] / st["stretch"], semitones=st["semitones"],
                              gain_db=st["gain_db"],
                              offset_seconds=max(0.0, st["offset_seconds"] - spec["start_seconds"])))
        unapplied += [[spec["section"], st["stem_id"], *e] for e in st.get("effects", [])]
    if picks:
        render(RenderRecipe(tuple(picks), float(spec["bpm"]), spec["key"], int(spec["seed"]),
                            sample_rate=sample_rate), out)
        audio, _ = sf.read(out, dtype="int16", always_2d=True)
    else:
        audio = np.zeros((0, 2), np.int16)
    audio = np.pad(audio[:length], ((0, max(0, length - len(audio))), (0, 0)))
    temp = out.with_suffix(f".{os.getpid()}.partial.wav")
    sf.write(temp, audio, sample_rate, subtype="PCM_16")
    atomic_replace(temp, out)
    out.with_suffix(".json").unlink(missing_ok=True)   # render()'s checkpoint no longer matches the trimmed file
    return out


def render_sections(specs: Iterable[dict], resolve: Resolver, cache_dir: str | Path, output: str | Path, *,
                    recipe_id: str, supersedes: str | None = None, sample_rate: int = 44100,
                    rerender: Iterable[int] = (), regenerate: Iterable[int] = (),
                    previous: dict | None = None) -> dict:
    """Render a recipe given every section's spec; reuse cached sections unless listed in ``rerender``."""
    cache_dir, output = Path(cache_dir), Path(output)
    cache_dir.mkdir(parents=True, exist_ok=True)
    specs = sorted(specs, key=lambda s: s["section"])
    rerender, regenerate = set(rerender), set(regenerate)
    old = {s["section"]: s for s in (previous or {}).get("sections", [])}
    hits, rendered, unapplied, parts = [], [], [], []
    for spec in specs:
        i = spec["section"]
        cached = _cache_file(cache_dir, spec["section_hash"], sample_rate)
        if i in regenerate:
            prev = old.get(i)
            src = _cache_file(cache_dir, prev["section_hash"], sample_rate) if prev else None
            parts.append((spec, src if src is not None and src.exists() else None))
        elif i not in rerender and cached.exists():
            hits.append(i)
            parts.append((spec, cached))
        else:
            rendered.append(i)
            parts.append((spec, _render_section(spec, resolve, cache_dir, sample_rate, unapplied)))
    total = round(max(s["end_seconds"] for s in specs) * sample_rate) if specs else 0
    mix = np.zeros((total, 2), np.int16)
    for spec, src in parts:
        a, b = round(spec["start_seconds"] * sample_rate), round(spec["end_seconds"] * sample_rate)
        if src is not None:
            audio, _ = sf.read(src, dtype="int16", always_2d=True)
            mix[a:b] = np.pad(audio[:b - a], ((0, max(0, b - a - len(audio))), (0, 0)))
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(f".{os.getpid()}.partial.wav")
    sf.write(temp, mix, sample_rate, subtype="PCM_16")
    atomic_replace(temp, output)
    manifest = {"version": VERSION, "renderer": RENDER_VERSION, "recipe_id": recipe_id, "supersedes": supersedes,
                "sample_rate": sample_rate, "duration_seconds": total / sample_rate, "sha256": file_hash(output),
                "rendered_sections": rendered, "reused_sections": hits, "regenerate_sections": sorted(regenerate),
                "unapplied_effects": unapplied, "sections": specs}
    atomic_json(output.with_suffix(".json"), manifest)
    return manifest


def render_recipe(recipe, resolve: Resolver, cache_dir: str | Path, output: str | Path, **kw) -> dict:
    """Full render of a planner ``Recipe`` (sections already in the cache are reused)."""
    from remixer.planner.plan import section_render_spec

    return render_sections([section_render_spec(s) for s in recipe.sections], resolve, cache_dir, output,
                           recipe_id=recipe.recipe_id, supersedes=recipe.supersedes,
                           regenerate=[s.index for s in recipe.sections if s.needs_regeneration], **kw)


def render_patch(request: dict, previous_manifest: dict, resolve: Resolver, cache_dir: str | Path,
                 output: str | Path) -> dict:
    """Apply ``Patch.render_request()`` on top of the previous version's render manifest."""
    if previous_manifest.get("recipe_id") != request["supersedes"]:
        raise ValueError("patch does not supersede the rendered version")
    specs = {s["section"]: s for s in previous_manifest["sections"]}
    specs.update({s["section"]: s for s in request["sections"]})
    return render_sections(specs.values(), resolve, cache_dir, output, recipe_id=request["recipe_id"],
                           supersedes=request["supersedes"], sample_rate=previous_manifest["sample_rate"],
                           rerender=[s["section"] for s in request["sections"]],
                           regenerate=request.get("needs_regeneration", ()), previous=previous_manifest)


def record_render(catalog, manifest: dict, recipe_version: int, blob_key: str | None = None) -> str:
    """Register a render under its recipe_id in the catalog's ``renders`` table."""
    render_id = manifest["sha256"]
    catalog.upsert("renders", {"render_id": render_id, "recipe_id": manifest["recipe_id"],
                               "recipe_version": recipe_version, "blob_key": blob_key,
                               "duration_s": manifest["duration_seconds"],
                               "renderer_version": f"{VERSION}/{manifest['renderer']}"}, key=["render_id"])
    return render_id


def load_manifest(output: str | Path) -> dict:
    return json.loads(Path(output).with_suffix(".json").read_text(encoding="utf-8"))

"""T-026: a patch re-renders only its listed sections and matches a full render of the new version."""
import dataclasses

import numpy as np
import pytest
import soundfile as sf

from remixer.cpu.patch_render import load_manifest, record_render, render_patch, render_recipe
from remixer.planner.model import Placement, Recipe, Section
from remixer.planner.plan import Patch

SR = 22050


@pytest.fixture
def stems(tmp_path):
    """Four 6-second stereo sine stems on disk."""
    paths = {}
    t = np.arange(6 * SR) / SR
    for name, f in (("drums", 110.0), ("bass", 55.0), ("bass2", 73.4), ("other", 440.0)):
        p = tmp_path / "stems" / f"{name}.wav"
        p.parent.mkdir(exist_ok=True)
        tone = 0.3 * np.sin(2 * np.pi * f * t) * (1 + 0.2 * np.sin(2 * np.pi * 2 * t))
        sf.write(p, np.stack([tone, tone], 1).astype(np.float32), SR, subtype="PCM_16")
        paths[f"song-{name}:{name.rstrip('2')}"] = p
    return paths


def place(stem_id: str, start_ms: int, stretch: float = 1.0, semis: int = 0) -> Placement:
    song, role = stem_id.split(":")
    return Placement(stem_id, song, role, 500, 2500, start_ms, start_ms + 2000, stretch=stretch,
                     shift_semitones=semis, gain_db=-1.0, effects=(("reverb_mix", 0.1),))


def recipe(bass_stem: str) -> Recipe:
    sections = tuple(
        Section(i, 2000 * i, 2000 * (i + 1), 120.0, "A minor", 4, 0.6, i + 1,
                (place("song-drums:drums", 2000 * i, 1.05),
                 *([place(bass_stem, 2000 * i, 0.95, -2)] if i == 1 else []),
                 place("song-other:other", 2000 * i)))
        for i in range(3))
    return Recipe(sections, seed=1, batch_id="b1", batch_slots=9)


def test_patch_touches_only_listed_sections_and_matches_full_render(tmp_path, stems):
    resolve = stems.__getitem__
    cache = tmp_path / "cache"
    v1 = recipe("song-bass:bass")
    first = render_recipe(v1, resolve, cache, tmp_path / "v1.wav", sample_rate=SR)
    assert first["rendered_sections"] == [0, 1, 2] and first["reused_sections"] == []
    assert [e[2] for e in first["unapplied_effects"]] == ["reverb_mix"] * len(list(v1.placements))

    new_sections = list(v1.sections)
    new_sections[1] = dataclasses.replace(v1.sections[1], placements=(
        v1.sections[1].placements[0], place("song-bass2:bass", 2000, 0.95, -2), v1.sections[1].placements[2]))
    v2 = Recipe(tuple(new_sections), 1, "b1", 9, lineage_id=v1.recipe_id, version=2, supersedes=v1.recipe_id)
    request = Patch(v1.recipe_id, v2, "ban", rerender=(1,), needs_regeneration=()).render_request()

    patched = render_patch(request, load_manifest(tmp_path / "v1.wav"), resolve, cache, tmp_path / "v2.wav")
    assert patched["rendered_sections"] == [1] and patched["reused_sections"] == [0, 2]
    assert patched["recipe_id"] == v2.recipe_id and patched["supersedes"] == v1.recipe_id

    full = render_recipe(v2, resolve, tmp_path / "fresh-cache", tmp_path / "v2-full.wav", sample_rate=SR)
    a, _ = sf.read(tmp_path / "v2.wav", dtype="int16")
    b, _ = sf.read(tmp_path / "v2-full.wav", dtype="int16")
    assert a.shape == b.shape == (3 * 2 * SR, 2)
    assert np.max(np.abs(a.astype(int) - b.astype(int))) <= 1
    old, _ = sf.read(tmp_path / "v1.wav", dtype="int16")
    assert np.array_equal(a[:2 * SR], old[:2 * SR]) and np.array_equal(a[4 * SR:], old[4 * SR:])
    assert not np.array_equal(a[2 * SR:4 * SR], old[2 * SR:4 * SR])
    assert full["sha256"] == patched["sha256"]


def test_regeneration_sections_keep_previous_audio_and_are_flagged(tmp_path, stems):
    resolve = stems.__getitem__
    v1 = recipe("song-bass:bass")
    render_recipe(v1, resolve, tmp_path / "c", tmp_path / "v1.wav", sample_rate=SR)
    hole = dataclasses.replace(v1.sections[1], placements=(v1.sections[1].placements[0],
                                                          v1.sections[1].placements[2]), needs_regeneration=True)
    v2 = Recipe((v1.sections[0], hole, v1.sections[2]), 1, "b1", 9, lineage_id=v1.recipe_id, version=2,
                supersedes=v1.recipe_id)
    req = Patch(v1.recipe_id, v2, "ban", rerender=(), needs_regeneration=(1,)).render_request()
    out = render_patch(req, load_manifest(tmp_path / "v1.wav"), resolve, tmp_path / "c", tmp_path / "v2.wav")
    assert out["regenerate_sections"] == [1] and out["rendered_sections"] == []
    a, _ = sf.read(tmp_path / "v2.wav", dtype="int16")
    old, _ = sf.read(tmp_path / "v1.wav", dtype="int16")
    assert np.array_equal(a, old)


def test_patch_must_supersede_the_rendered_version(tmp_path, stems):
    v1 = recipe("song-bass:bass")
    m = render_recipe(v1, stems.__getitem__, tmp_path / "c", tmp_path / "v1.wav", sample_rate=SR)
    with pytest.raises(ValueError):
        render_patch({"recipe_id": "x", "supersedes": "not-v1", "sections": []}, m, stems.__getitem__,
                     tmp_path / "c", tmp_path / "x.wav")


def test_render_is_recorded_under_the_recipe_id(tmp_path, stems):
    from remixer.adapters.sqlite_catalog import SqliteCatalog

    v1 = recipe("song-bass:bass")
    m = render_recipe(v1, stems.__getitem__, tmp_path / "c", tmp_path / "v1.wav", sample_rate=SR)
    cat = SqliteCatalog(tmp_path / "catalog.sqlite")
    try:
        rid = record_render(cat, m, v1.version, "renders/v1")
        assert cat.get("renders", render_id=rid)["recipe_id"] == v1.recipe_id
    finally:
        cat.close()

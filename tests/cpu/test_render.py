from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from remixer.corpus.generate import TrackSpec, generate_track
from remixer.cpu.assemble import Recipe, StemPick, assemble
from remixer.cpu.render import render


def test_seeded_assembly_and_byte_identical_rubberband(tmp_path):
    row = generate_track(TrackSpec(11, duration=2, sample_rate=8000, bpm=100), tmp_path / "source")
    recipe = replace(assemble([row], seed=42, duration=1, bpm=120), sample_rate=8000)
    assert recipe == Recipe.from_dict(recipe.to_dict())
    assert recipe.identity == Recipe.from_dict(recipe.to_dict()).identity
    assert assemble([row], seed=42, duration=1, bpm=120).identity == assemble([row], seed=42, duration=1, bpm=120).identity
    a = render(recipe, tmp_path / "a.wav")
    b = render(recipe, tmp_path / "b.wav")
    assert a["sha256"] == b["sha256"]
    assert a["duration_seconds"] == pytest.approx(1, abs=.01)
    with pytest.raises(ValueError, match="overwrite source"):
        render(recipe, row["paths"]["drums"])
    Path(row["paths"]["drums"]).write_bytes(b"changed source")
    with pytest.raises(ValueError, match="source hash"):
        render(recipe, tmp_path / "c.wav")


def test_pitch_shift_preserves_duration_and_changes_frequency(tmp_path):
    from remixer.corpus.generate import file_hash
    sr = 16000
    t = np.arange(sr * 2) / sr
    source = tmp_path / "tone.wav"
    sf.write(source, .2 * np.sin(2 * np.pi * 440 * t), sr, subtype="PCM_16")
    pick = StemPick(str(source), file_hash(source), "vocals", 0, 2, 100, 12)
    recipe = Recipe((pick,), 100, "A major", sample_rate=sr)
    result = render(recipe, tmp_path / "pitched.wav")
    audio, _ = sf.read(tmp_path / "pitched.wav")
    frequency = np.fft.rfftfreq(len(audio), 1 / sr)[np.argmax(np.abs(np.fft.rfft(audio.mean(axis=1))))]
    assert frequency == pytest.approx(880, abs=5)
    assert result["duration_seconds"] == pytest.approx(2, abs=.01)


def test_recipe_provenance_follows_selected_sources(monkeypatch, tmp_path):
    row = generate_track(TrackSpec(5, duration=1, sample_rate=8000), tmp_path)
    real = {**row, "synthetic": False, "augmented": True}
    class PickFirst:
        def integers(self, *args, **kwargs):
            return 0
    monkeypatch.setattr("remixer.cpu.assemble.np.random.default_rng", lambda seed: PickFirst())
    recipe = assemble([real, row])
    assert not recipe.synthetic
    assert recipe.augmented

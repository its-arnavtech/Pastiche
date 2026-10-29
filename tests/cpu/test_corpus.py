from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest
import soundfile as sf

from remixer.corpus.generate import TrackSpec, file_hash, generate_track, synth_block, write_manifest


def test_true_stems_and_determinism(tmp_path):
    spec = TrackSpec(19, duration=2, sample_rate=8000)
    first = generate_track(spec, tmp_path / "a", block_size=1000)
    second = generate_track(spec, tmp_path / "b", block_size=777)
    assert first["hashes"] == second["hashes"]
    mix, sr = sf.read(first["paths"]["mix"], dtype="int16", always_2d=True)
    stems = [sf.read(first["paths"][name], dtype="int16", always_2d=True)[0].astype(np.int32)
             for name in first["stem_layout"]]
    np.testing.assert_array_equal(mix, sum(stems))
    assert sr == 8000 and len(mix) == 16000
    assert first["synthetic"] and not first["real"]
    assert len(first["beat_positions"]) >= 2
    assert generate_track(spec, tmp_path / "a")["hashes"] == first["hashes"]
    Path(first["paths"]["drums"]).write_bytes(b"corrupt")
    assert generate_track(spec, tmp_path / "a")["hashes"] == first["hashes"]
    manifest = write_manifest(tmp_path, [first])
    assert pq.read_table(manifest).to_pylist()[0]["key"] == first["key"]


def test_generator_rejects_invalid_audio(tmp_path):
    with pytest.raises(ValueError):
        generate_track(TrackSpec(1, duration=0), tmp_path)
    with pytest.raises(ValueError):
        generate_track(TrackSpec(1, bpm=0), tmp_path)


def test_atomic_checkpoint_retries_transient_windows_sharing(monkeypatch, tmp_path):
    import json
    from remixer.corpus.generate import atomic_json
    original, attempts = Path.replace, []
    def sharing_once(source, destination):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError("temporary reader sharing violation")
        return original(source, destination)
    monkeypatch.setattr(Path, "replace", sharing_once)
    atomic_json(tmp_path / "checkpoint.json", {"completed": 3})
    assert len(attempts) == 3
    assert json.loads((tmp_path / "checkpoint.json").read_text()) == {"completed": 3}


def test_arrangements_vary_harmony_and_rhythm_without_changing_legacy_identity(tmp_path):
    import hashlib
    import json
    spec = TrackSpec(4, duration=2, sample_rate=8000)
    values = spec.resolved()
    assert "arrangement" not in values
    legacy = generate_track(spec, tmp_path / "legacy")
    assert legacy["track_id"] == hashlib.sha256(("procedural-v1" + json.dumps(values, sort_keys=True)).encode()).hexdigest()
    a = generate_track(TrackSpec(4, duration=2, sample_rate=8000, arrangement=1), tmp_path / "varied")
    b = generate_track(TrackSpec(4, duration=2, sample_rate=8000, arrangement=2), tmp_path / "varied")
    assert a["version"] == b["version"] == "procedural-v2"
    assert a["chord_progression_degrees"] != b["chord_progression_degrees"]
    assert a["drum_pattern"] != b["drum_pattern"]
    assert a["hashes"]["drums"] != b["hashes"]["drums"]

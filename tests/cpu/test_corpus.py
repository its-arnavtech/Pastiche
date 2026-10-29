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

import numpy as np
import pyloudnorm as pyln
import pytest
import soundfile as sf

from remixer.corpus.generate import TrackSpec, generate_track
from remixer.cpu.analyze import analyze_file, estimate_key, estimate_tempo, MAJOR, MINOR


def test_key_templates_and_silence():
    assert estimate_key(np.roll(MAJOR, 7))[0] == "G major"
    assert estimate_key(np.roll(MINOR, 9))[0] == "A minor"
    assert estimate_key(np.zeros(12)) == (None, 0)
    assert estimate_tempo(np.zeros(22050)) == (None, [])


def test_mmap_analysis_matches_bs1770(tmp_path):
    sr = 8000
    t = np.arange(sr * 12) / sr
    audio = np.column_stack((.2 * np.sin(2 * np.pi * 440 * t), .1 * np.sin(2 * np.pi * 523.25 * t)))
    path = tmp_path / "tone.wav"
    sf.write(path, audio, sr, subtype="PCM_16")
    actual_audio, _ = sf.read(path, always_2d=True)
    result = analyze_file(path, tmp_path / "features.json")
    assert result["lufs"] == pytest.approx(pyln.Meter(sr).integrated_loudness(actual_audio), abs=.01)
    assert len(result["windows"]) == 3
    assert result["windows"][-1]["duration_seconds"] == 2
    assert result == analyze_file(path, tmp_path / "features.json")


@pytest.mark.parametrize("bpm", [75, 100, 140, 170])
def test_tempo_against_seeded_ground_truth(tmp_path, bpm):
    row = generate_track(TrackSpec(3, duration=12, sample_rate=8000, bpm=bpm), tmp_path)
    result = analyze_file(row["paths"]["mix"])
    assert result["bpm"] == pytest.approx(bpm, abs=2)
    assert result["beat_positions"]


def test_durable_analysis_is_idempotent(tmp_path):
    from remixer.adapters.sqlite_queue import SqliteJobQueue
    from remixer.cpu.analyze import drain_analysis, enqueue_analysis
    row = generate_track(TrackSpec(88, duration=1, sample_rate=8000), tmp_path / "source")
    queue = SqliteJobQueue(tmp_path / "jobs.sqlite")
    try:
        assert enqueue_analysis(queue, [row], tmp_path / "features") == 5
        assert enqueue_analysis(queue, [row], tmp_path / "features") == 0
        assert drain_analysis(queue, workers=1)["counts"] == {"done": 5}
        assert drain_analysis(queue, workers=1)["completed"] == 0
    finally:
        queue.close()

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


@pytest.mark.parametrize("bpm", [70, 75, 100, 138, 140, 150, 154, 159, 164, 169, 170, 175])
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
        import json
        saved = json.loads((tmp_path / "features" / row["track_id"] / "mix.json").read_text())
        assert saved["synthetic"] is True and saved["real"] is False
        assert all(window["synthetic"] is True for window in saved["windows"])
        from remixer.cpu.analyze import write_track_summaries
        assert write_track_summaries([row], tmp_path / "features") == 1
        track = json.loads((tmp_path / "features" / row["track_id"] / "track.json").read_text())
        assert track["synthetic"] is True and track["real"] is False
        assert drain_analysis(queue, workers=1)["completed"] == 0
    finally:
        queue.close()


def test_track_summary_uses_harmony_and_percussion_without_labels():
    from remixer.cpu.analyze import combine_stem_features
    result = combine_stem_features({"mix": {"key": "F minor", "bpm": 75, "beat_positions": [], "lufs": -16},
                                    "other": {"key": "C minor"},
                                    "drums": {"bpm": 150, "beat_positions": [0, .4]}})
    assert result["key"] == "C minor" and result["key_source"] == "other"
    assert result["bpm"] == 150 and result["tempo_source"] == "drums"
    assert result["mix_only_key"] == "F minor" and result["mix_only_bpm"] == 75


@pytest.mark.parametrize("mix,drums,bass,expected", [(165, 110, 165, 165), (164, 82, 164, 164), (168, 168, 84, 84)])
def test_track_pulse_consensus_rejects_syncopated_subdivisions(mix, drums, bass, expected):
    from remixer.cpu.analyze import combine_stem_features
    result = combine_stem_features({"mix": {"bpm": mix, "beat_positions": []},
                                    "drums": {"bpm": drums, "beat_positions": []},
                                    "bass": {"bpm": bass, "beat_positions": []}})
    assert result["bpm"] == expected
    assert result["tempo_source"] == "bass"

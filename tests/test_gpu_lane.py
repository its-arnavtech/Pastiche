"""GPU-lane logic that runs without a GPU: overlap-add, chunking, batch sizing, ingest, telemetry."""
from __future__ import annotations

import json
import types

import numpy as np
import pytest
import torch

from remixer.gpu.separate import Separator, TrackState, chunk, n_chunks
from remixer.gpu.vram import BatchSizer


def stub_runner(segment=1000, overlap=0.25):
    half = segment // 2
    tri = torch.cat([torch.arange(1, half + 1), torch.arange(segment - half, 0, -1)]).float()
    return types.SimpleNamespace(segment=segment, stride=int(segment * (1 - overlap)), sources=["a", "b"],
                                 window=tri / tri.max(), device="cpu", sr=1000)


@pytest.mark.parametrize("frames", [400, 1000, 2600, 3333])
def test_overlap_add_reconstructs_identity(frames):
    R = stub_runner()
    sep = Separator.__new__(Separator)
    sep.runner = R
    rng = np.random.default_rng(0)
    audio = torch.from_numpy(rng.uniform(-0.5, 0.5, (2, frames)).astype(np.float32))
    st = TrackState(item=None, norm=audio, mean=0.0, std=1.0, frames=frames,
                    n_chunks=n_chunks(frames, R.segment, R.stride))
    st.acc = torch.zeros(2, 2, R.segment)
    st.wsum = torch.zeros(R.segment)
    parts = []
    for k in range(st.n_chunks):
        x = chunk(st, k, R.segment, R.stride)
        y = torch.stack([x, -x])  # "model": source a = mix, source b = -mix
        if (out := sep._accumulate(st, k, y)) is not None:
            parts.append(out)
    got = np.concatenate(parts, axis=-1)
    assert got.shape == (2, 2, frames)
    expect = np.clip(np.rint(audio.numpy() * 32767), -32768, 32767)
    assert np.abs(got[0] - expect).max() <= 1 and np.abs(got[1] + expect).max() <= 1


def test_n_chunks_covers_track():
    for frames in (1, 999, 1000, 1001, 5000):
        n = n_chunks(frames, 1000, 750)
        assert (n - 1) * 750 + 1000 >= frames and (n == 1 or (n - 2) * 750 + 1000 < frames)


def test_batch_sizer_calibrate_stops_at_spill(tmp_path):
    s = BatchSizer(tmp_path / "s.json", "k", margin_bytes=0)
    peak = lambda b: 100 + 10 * b  # noqa: E731
    # throughput rises to batch 8 then collapses (sysmem spill)
    secs = lambda b: b / (b if b <= 8 else 1.0)  # noqa: E731
    assert s.calibrate(peak, secs, available=10_000) == 8
    assert BatchSizer(tmp_path / "s.json", "k").batch == 8  # remembered
    assert s.on_oom() == 4


def test_batch_sizer_memory_bound(tmp_path):
    s = BatchSizer(tmp_path / "s.json", "k", margin_bytes=50)
    assert s.size(lambda b: 100 + 10 * b, available=300) == 15  # base 100, 10/item: (300-50-100)/10


def test_ingest_corpus_registers_and_enqueues(data_dir):
    from remixer.adapters import build
    from remixer.ingest import ingest_corpus

    corpus = data_dir / "corpus"
    for i in range(3):
        d = corpus / f"t{i}"
        d.mkdir(parents=True)
        (d / "mix.wav").write_bytes(b"RIFF")
        (d / "track.json").write_text(json.dumps({
            "track_id": f"t{i}", "hashes": {"mix": f"h{i}"}, "paths": {"mix": str(d / "mix.wav")},
            "duration": 1.0, "sample_rate": 44100, "bpm": 120, "key": "C major"}))
    (corpus / "partial").mkdir()
    (corpus / "partial" / "track.json").write_text("{not json")
    a = build()
    assert ingest_corpus(a, corpus) == {"registered": 3, "enqueued": 3}
    assert ingest_corpus(a, corpus)["enqueued"] == 0  # idempotent
    assert a.catalog.get("tracks", track_id="h1")["synthetic"] == 1


def test_queue_release_does_not_count_attempt(tmp_path):
    from remixer.adapters.sqlite_queue import SqliteJobQueue

    q = SqliteJobQueue(tmp_path / "q.sqlite", max_attempts=1)
    q.enqueue("k", "a")
    j = q.lease("k", "w")[0]
    q.release(j.id)
    assert q.lease("k", "w2")[0].attempts == 1


def test_dashboard_renders(tmp_path):
    import pyarrow as pa

    from remixer.telemetry.dashboard import render

    t = pa.table({"ts": [0.0, 1.0, 2.0], "tag": ["a", "a", "b"], "gpu_util": [10, None, 90],
                  "cpu_00": [1.0, 2.0, 3.0], "cpu_01": [4.0, 5.0, 6.0], "cpu_util": [2.5, 3.5, 4.5]})
    html = render(t, tmp_path / "d.html").read_text()
    assert "gpu_util" in html and '"tags": [[0.0, 2.0, "a"], [2.0, 2.0, "b"]]' in html

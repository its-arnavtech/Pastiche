"""Taste trainer: learns a planted direction, and synthetic/real ratings never mix."""
from __future__ import annotations

import numpy as np
import pytest

from remixer.adapters import build
from remixer.gpu import taste


@pytest.fixture
def fake_embeddings(data_dir):
    a = build()
    mv = "fake@1"
    rng = np.random.default_rng(1)
    root = data_dir / "embeddings" / "fake_1"
    root.mkdir(parents=True)
    for s in range(40):
        stem = f"stem{s}"
        v = rng.standard_normal((30, 32)).astype(np.float16)
        np.save(root / f"{stem}.npy", v)
        for w in range(30):
            a.catalog.upsert("windows", {"window_id": f"{stem}-{w}", "owner_id": stem, "owner_kind": "stem",
                                         "start_ms": w * 5000, "end_ms": w * 5000 + 5000, "model_version": mv},
                             key=["window_id"])
    return a, mv


def test_learns_planted_taste(fake_embeddings):
    a, mv = fake_embeddings
    ids, vecs = taste.load_window_vectors(a, mv)
    assert len(ids) == 1200 and vecs.shape == (1200, 32)
    taste.synthesize_ratings(a, ids, vecs, frac=0.8, seed=3)
    res = taste.train(a, "synthetic", model_version=mv, epochs=60, batch=256, width=64, seed=3)
    assert res.val_auc > 0.85 and res.truth_cos > 0.8


def test_synthetic_and_real_never_mix(fake_embeddings):
    a, _ = fake_embeddings
    a.catalog.insert("rating_events", {"event_id": "r1", "target_kind": "window", "target_id": "stem0-0",
                                       "rating": "up", "wall_time": "t", "synthetic": 1})
    assert taste.load_ratings(a, "real") == []  # the synthetic row is excluded from real data
    a.events.append("synthetic_ratings", [{"event_id": "x", "target_id": "stem0-0", "rating": "up", "synthetic": False}])
    with pytest.raises(AssertionError):
        taste.load_ratings(a, "synthetic")


def test_auc():
    assert taste.auc(np.array([.1, .4, .35, .8]), np.array([0, 0, 1, 1])) == 0.75


def test_old_version_ratings_do_not_prevent_planting(fake_embeddings, monkeypatch):
    a, mv = fake_embeddings
    a.events.append("synthetic_ratings", [{"event_id": "old", "target_id": "old-version-window",
                                          "rating": "up", "synthetic": True}])
    # Stop before device allocation: this tests the version boundary, without GPU work.
    original = taste.synthesize_ratings

    def plant(adapters, ids, vecs, **kwargs):
        result = original(adapters, ids, vecs, **kwargs)
        raise RuntimeError("fresh ratings planted")

    monkeypatch.setattr(taste, "synthesize_ratings", plant)
    with pytest.raises(RuntimeError, match="fresh ratings planted"):
        taste.train(a, "synthetic", model_version=mv)
    rows = a.events.read("synthetic_ratings")
    assert any(r["target_id"].startswith("stem") for r in rows)
    assert any(r["event_id"].startswith("syn-0-stem") for r in rows)


def test_nonfinite_embedding_is_rejected(fake_embeddings):
    a, mv = fake_embeddings
    root = a.profile.data_dir / "embeddings" / mv.replace("@", "_")
    values = np.load(root / "stem0.npy")
    values[0, 0] = np.nan
    np.save(root / "stem0.npy", values)
    with pytest.raises(ValueError, match="nonfinite CLAP"):
        taste.load_window_vectors(a, mv)


def test_checkpoint_from_other_embedding_version_is_kept(tmp_path):
    import torch

    out = tmp_path / "taste-mlp-v1-synthetic-w256.pt"
    torch.save({"embedding_model": "clap@old"}, out)
    np.savez(out.with_suffix(".npz"), w=np.zeros(1))
    kept = taste.set_aside_superseded(out, "clap@new")
    assert kept is not None and kept.exists() and kept.with_suffix(".npz").exists() and not out.exists()
    torch.save({"embedding_model": "clap@new"}, out)
    assert taste.set_aside_superseded(out, "clap@new") is None and out.exists()

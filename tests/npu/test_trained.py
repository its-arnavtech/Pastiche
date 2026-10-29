from pathlib import Path

import numpy as np
import pytest
import torch

from remixer.gpu.taste import build_mlp
from remixer.npu.scorer import OpenVINOScorer, ScorerSpec, export_scorer, resolve_spec
from remixer.npu.trained import TasteWeights


def checkpoint(path: Path, corrupt=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(18)
    model = build_mlp(4, 8).eval()
    metadata = {"state_dict": model.state_dict(), "width": 8, "dim": 4, "kind": "synthetic",
                "synthetic": True, "embedding_model": "fixture-only", "version": "fixture-only"}
    torch.save(metadata, path.with_suffix(".pt"))
    arrays = {key: value.detach().numpy().copy() for key, value in model.state_dict().items()}
    if corrupt:
        arrays["0.weight"][0, 0] = np.nan
    np.savez(path, **arrays)
    return model


def test_gelu_bias_export_preserves_coordinator_network(tmp_path):
    path = tmp_path / "fixture.npz"
    model = checkpoint(path)
    values = np.random.default_rng(1).normal(size=(4, 4)).astype(np.float32)
    with torch.no_grad():
        expected = torch.sigmoid(model(torch.from_numpy(values))).numpy()
    bundle = TasteWeights.load(path)
    np.testing.assert_allclose(bundle.predict(values), expected, atol=1e-6)
    spec = ScorerSpec.trained(path, batch=4)
    ir = export_scorer(tmp_path / "ir", spec)
    np.testing.assert_allclose(OpenVINOScorer(ir, spec, "CPU").score(values), expected, atol=1e-5)


def test_invalid_trained_weights_never_become_fitness(tmp_path, monkeypatch, caplog):
    path = tmp_path / "models/taste/taste-mlp-v1-synthetic-w256.npz"
    checkpoint(path, corrupt=True)
    with pytest.raises(ValueError, match="finite"):
        TasteWeights.load(path)
    monkeypatch.setenv("REMIXER_DATA_DIR", str(tmp_path))
    assert resolve_spec().weights_path is None
    assert "unusable" in caplog.text
    with pytest.raises(ValueError, match="finite"):
        resolve_spec(path)

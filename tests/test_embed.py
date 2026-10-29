"""CLAP GPU front end must match transformers' ClapFeatureExtractor (runs on CPU)."""
from __future__ import annotations

import numpy as np
import pytest
import torch

from remixer.gpu.embed import CLAP_LEN, CLAP_SR, ClapFrontEnd, repeat_pad


def test_repeat_pad_matches_clap_rule():
    x = torch.arange(1, 4, dtype=torch.float32)[None]  # n=3
    y = repeat_pad(x, 10)
    assert y.tolist() == [[1, 2, 3, 1, 2, 3, 1, 2, 3, 0]]
    assert repeat_pad(torch.ones(1, 12), 10).shape == (1, 10)


@pytest.mark.slow
def test_front_end_matches_feature_extractor():
    transformers = pytest.importorskip("transformers")
    try:
        fe = transformers.ClapFeatureExtractor.from_pretrained("laion/clap-htsat-unfused", local_files_only=True)
    except Exception:
        pytest.skip("CLAP preprocessor config not cached")
    rng = np.random.default_rng(0)
    wave = (rng.standard_normal(5 * CLAP_SR) * 0.1).astype(np.float32)
    ref = fe(wave, sampling_rate=CLAP_SR, return_tensors="np")["input_features"]  # (1, 1, frames, 64)
    ours = ClapFrontEnd(fe.mel_filters_slaney, "cpu")(repeat_pad(torch.from_numpy(wave)[None], CLAP_LEN)).numpy()
    assert ours.shape == ref.shape
    assert np.abs(ours - ref).max() < 1e-2

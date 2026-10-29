"""Portable inference for the coordinator's versioned GELU taste checkpoints."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.special import erf, expit

from remixer.corpus.generate import file_hash


@dataclass
class TasteWeights:
    arrays: dict[str, np.ndarray]
    metadata: dict
    identity: str

    @classmethod
    def load(cls, path: str | Path):
        import torch
        path = Path(path)
        metadata = torch.load(path.with_suffix(".pt"), map_location="cpu", weights_only=True)
        metadata = {key: value for key, value in metadata.items() if key != "state_dict"}
        if metadata.get("kind") not in {"synthetic", "real"} or bool(metadata.get("synthetic")) != (metadata["kind"] == "synthetic"):
            raise ValueError("taste checkpoint training provenance is missing or inconsistent")
        with np.load(path, allow_pickle=False) as archive:
            arrays = {name: np.asarray(archive[name], dtype=np.float32) for name in archive.files}
        previous = int(metadata["dim"])
        for layer in (0, 3, 5):
            weight, bias = arrays[f"{layer}.weight"], arrays[f"{layer}.bias"]
            if weight.ndim != 2 or weight.shape[1] != previous or bias.shape != (weight.shape[0],):
                raise ValueError("taste checkpoint layer dimensions are inconsistent")
            if not np.isfinite(weight).all() or not np.isfinite(bias).all():
                raise ValueError("taste weights must be finite")
            previous = weight.shape[0]
        if previous != 1:
            raise ValueError("taste checkpoint must produce one logit")
        return cls(arrays, metadata, file_hash(path))

    def predict(self, embeddings: np.ndarray) -> np.ndarray:
        value = np.asarray(embeddings, dtype=np.float32)
        if value.ndim != 2 or value.shape[1] != self.metadata["dim"]:
            raise ValueError("embedding width does not match trained taste model")
        if not np.isfinite(value).all():
            raise ValueError("taste input embeddings must be finite")
        for layer in (0, 3, 5):
            value = value @ self.arrays[f"{layer}.weight"].T + self.arrays[f"{layer}.bias"]
            if layer != 5:
                value = .5 * value * (1 + erf(value / np.float32(np.sqrt(2))))
        return expit(value).astype(np.float32)

"""One parent-process CLAP encoder plus the trained, provenance-checked scorer."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from remixer.npu.trained import TasteWeights


class ClapTasteScorer:
    """Batch fitness adapter: workers render; one CPU model scores all clips.

    Five-second windows, repeat-padding, projection and L2 normalization match
    the coordinator's encoder. No CUDA model or duplicate encoder per worker.
    """

    def __init__(self, weights_path: Path, threads: int = 1, batch_size: int = 2):
        self.weights = TasteWeights.load(weights_path)
        self.embedding_version = self.weights.metadata["embedding_model"]
        self.model_name = self.embedding_version.split("@", 1)[0]
        self.threads = max(1, threads)
        self.batch_size = max(1, batch_size)
        self.identity = f"clap-taste-v1:{self.embedding_version}:{self.weights.identity}"
        self.training_kind = self.weights.metadata["kind"]
        self._ready = False

    def _load(self):
        import torch
        from transformers import ClapFeatureExtractor, ClapModel
        from remixer.gpu.embed import ClapFrontEnd, model_version
        if model_version(self.model_name) != self.embedding_version:
            raise ValueError("trained taste embeddings and current CLAP version differ")
        torch.set_num_threads(self.threads)
        extractor = ClapFeatureExtractor.from_pretrained(self.model_name, local_files_only=True)
        self.front = ClapFrontEnd(extractor.mel_filters_slaney, "cpu")
        model = ClapModel.from_pretrained(self.model_name, local_files_only=True)
        self.audio = model.audio_model.to("cpu").eval()
        self.projection = model.audio_projection.to("cpu").eval()
        del model
        self._ready = True

    def score_batch(self, audios: list[np.ndarray], sample_rate: int) -> list[float]:
        import torch
        import torch.nn.functional as F
        import julius
        from remixer.gpu.embed import CLAP_SR, repeat_pad
        if not self._ready:
            self._load()
        windows, owners, durations = [], [], []
        for owner, audio in enumerate(audios):
            mono = np.asarray(audio, dtype=np.float32)
            if mono.ndim == 2:
                mono = mono.mean(axis=1)
            for start in range(0, len(mono), sample_rate * 5):
                part = mono[start:start + sample_rate * 5]
                if not len(part):
                    continue
                wave = torch.from_numpy(np.ascontiguousarray(part)).unsqueeze(0)
                if sample_rate != CLAP_SR:
                    wave = julius.resample_frac(wave, sample_rate, CLAP_SR)
                windows.append(repeat_pad(wave))
                owners.append(owner)
                durations.append(len(part) / sample_rate)
        totals, weights = np.zeros(len(audios)), np.zeros(len(audios))
        with torch.inference_mode():
            for start in range(0, len(windows), self.batch_size):
                wave = torch.cat(windows[start:start + self.batch_size])
                pooled = self.audio(input_features=self.front(wave)).pooler_output
                embeddings = F.normalize(self.projection(pooled).float(), dim=-1).numpy()
                scores = self.weights.predict(embeddings).reshape(-1)
                for index, score in enumerate(scores, start):
                    totals[owners[index]] += float(score) * durations[index]
                    weights[owners[index]] += durations[index]
        return (totals / np.maximum(weights, 1e-12)).tolist()

    def score(self, audio: np.ndarray, sample_rate: int) -> float:
        return self.score_batch([audio], sample_rate)[0]

"""Synthetic stem-metadata library for tests and the scale run (no audio, ``synthetic`` ids).

Songs belong to genre clusters with realistic tempo ranges and meters; keys are uniform over the
12 tonics with about 45 percent minor. Each song has drums, bass and other stems and usually
vocals. Embeddings: cluster centre + song offset + a per-role direction + noise, unit-normalised,
so stems of one song, one role and one cluster are near each other.
"""
from __future__ import annotations

import numpy as np

from .catalog import InMemoryCatalog, StemMeta
from .model import ROLES, key_name

# name, bpm mean, bpm sd, P(3/4), energy mean
GENRES = (
    ("house", 124.0, 2.5, 0.0, 0.72),
    ("techno", 130.0, 3.0, 0.0, 0.8),
    ("pop", 112.0, 12.0, 0.05, 0.6),
    ("hiphop", 92.0, 7.0, 0.0, 0.55),
    ("dnb", 174.0, 2.0, 0.0, 0.85),
    ("rock", 128.0, 16.0, 0.05, 0.7),
    ("downtempo", 88.0, 8.0, 0.1, 0.35),
    ("ballad", 72.0, 8.0, 0.45, 0.3),
)
ROLE_ENERGY = {"drums": 0.05, "bass": 0.0, "vocals": -0.02, "other": -0.06}


def synthetic_library(n_songs: int, seed: int = 0, dim: int = 32, n_clusters: int = 24,
                      vocal_fraction: float = 0.8) -> InMemoryCatalog:
    rng = np.random.default_rng(seed)
    centers = rng.normal(size=(n_clusters, dim))
    role_dirs = {r: rng.normal(size=dim) for r in ROLES}
    stems: list[StemMeta] = []
    for i in range(n_songs):
        c = int(rng.integers(n_clusters))
        _, mu, sd, p3, e_mu = GENRES[c % len(GENRES)]
        bpm = round(float(np.clip(rng.normal(mu, sd), 60.0, 190.0)), 2)
        pc, minor = int(rng.integers(12)), bool(rng.random() < 0.45)
        meter = 3 if rng.random() < p3 else 4
        duration = int(rng.integers(150_000, 300_000))
        downbeat = int(rng.integers(0, int(meter * 60_000 / bpm)))
        energy = float(np.clip(rng.normal(e_mu, 0.12), 0.02, 0.98))
        song_vec = centers[c] + 0.6 * rng.normal(size=dim)
        song_id = f"song-{i:05d}"
        has_vocals = rng.random() < vocal_fraction
        for role in ROLES:
            if role == "vocals" and not has_vocals:
                continue
            emb = song_vec + 0.5 * role_dirs[role] + 0.3 * rng.normal(size=dim)
            emb = (emb / np.linalg.norm(emb)).astype(np.float32)
            emb.setflags(write=False)
            stems.append(StemMeta(
                stem_id=f"{song_id}:{role}", song_id=song_id, role=role, bpm=bpm, key=key_name(pc, minor),
                meter=meter, downbeat_ms=downbeat, loudness_lufs=round(float(rng.normal(-16.0, 3.0)), 2),
                energy=round(float(np.clip(energy + ROLE_ENERGY[role] + rng.normal(0, 0.08), 0.0, 1.0)), 4),
                duration_ms=duration, embedding=emb))
    return InMemoryCatalog(stems)

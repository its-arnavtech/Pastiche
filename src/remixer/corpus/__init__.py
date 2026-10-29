"""Seeded synthetic audio and ground-truth stems (never real taste data)."""

from .generate import TrackSpec, generate_corpus, generate_track

__all__ = ["TrackSpec", "generate_corpus", "generate_track"]

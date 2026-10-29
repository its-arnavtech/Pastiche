"""Playback event analytics: schema, interpretation, skip heatmap, simulator (T-014)."""
from .events import EVENT_FIELDS, EVENT_TYPES, PLAYBACK_EVENT_TYPES, SEEK_MS, Event, validate_event
from .heatmap import DetectorConfig, HeatmapBuilder, WindowStats, build_heatmap, detect_candidates
from .interpret import InterpretConfig, Listen, Signal, interpret, interpret_session

__all__ = [
    "EVENT_FIELDS", "EVENT_TYPES", "PLAYBACK_EVENT_TYPES", "SEEK_MS", "Event", "validate_event",
    "DetectorConfig", "HeatmapBuilder", "WindowStats", "build_heatmap", "detect_candidates",
    "InterpretConfig", "Listen", "Signal", "interpret", "interpret_session",
]

"""Upgrade ambiguous tempi and derive track estimates from analyzed stems.

Runs in one process so it fits the tooling reserve while lane benchmarks run.
Ground truth is used only to score the final independently computed estimates.
"""
from __future__ import annotations

import json
import argparse
from pathlib import Path
import time

import numpy as np
import pyarrow.parquet as pq

from remixer.corpus.generate import atomic_json
from remixer.cpu.analyze import VERSION, combine_stem_features, upgrade_tempo, with_provenance


def main():
    from remixer.config import data_dir
    data = data_dir()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=data / "corpus")
    parser.add_argument("--analysis", type=Path, default=data / "analysis")
    args = parser.parse_args()
    root = args.analysis
    baseline = json.loads((root / "benchmark.json").read_text())
    if not (root / "baseline-v2.json").exists():
        atomic_json(root / "baseline-v2.json", baseline)
    rows = pq.read_table(args.corpus / "manifest.parquet").to_pylist()
    scores, mix_scores = [], []
    started = time.perf_counter()
    for index, row in enumerate(rows):
        features = {}
        for stem in row["paths"]:
            path = root / row["track_id"] / f"{stem}.json"
            value = json.loads(path.read_text())
            if stem in {"drums", "mix", "bass"} and value["version"] != VERSION:
                value = upgrade_tempo(Path(row["paths"][stem]), value)
            value = with_provenance(value, {name: row.get(name) for name in ("synthetic", "augmented", "real")})
            atomic_json(path, value)
            features[stem] = value
        combined = combine_stem_features(features)
        atomic_json(root / row["track_id"] / "track.json", combined)
        scores.append({"track_id": row["track_id"], "bpm_error": abs(combined["bpm"] - row["bpm"]) if combined["bpm"] else None,
                       "key_correct": combined["key"] == row["key"]})
        mix_scores.append({"bpm_error": abs(features["mix"]["bpm"] - row["bpm"]) if features["mix"]["bpm"] else None,
                           "key_correct": features["mix"]["key"] == row["key"]})
        if (index + 1) % 25 == 0:
            print(json.dumps({"refined_tracks": index + 1, "target": len(rows)}), flush=True)
    result = {**baseline, "mean_bpm_error": float(np.mean([row["bpm_error"] for row in scores if row["bpm_error"] is not None])),
              "key_accuracy": float(np.mean([row["key_correct"] for row in scores])),
              "mix_mean_bpm_error": float(np.mean([row["bpm_error"] for row in mix_scores if row["bpm_error"] is not None])),
              "mix_key_accuracy": float(np.mean([row["key_correct"] for row in mix_scores])), "scores": scores,
              "accuracy_method": "key from harmonic other stem; drum/mix/bass tempo agreement with octave resolution; no truth labels used during inference",
              "refinement_seconds": baseline.get("refinement_seconds", 0) + time.perf_counter() - started,
              "throughput_note": "original full analysis invocation; later single-process estimate refinement timed separately"}
    atomic_json(root / "benchmark.json", result)
    print(json.dumps({key: result[key] for key in ("mean_bpm_error", "key_accuracy", "mix_mean_bpm_error", "mix_key_accuracy", "refinement_seconds")}, indent=2))


if __name__ == "__main__":
    main()

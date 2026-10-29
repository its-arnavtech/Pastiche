"""Inspect synthetic analysis errors without using labels during inference."""
from collections import Counter
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq


def main():
    from remixer.config import data_dir
    data_root = data_dir()
    rows = pq.read_table(data_root / "corpus/manifest.parquet").to_pylist()
    by_stem = {}
    confusion = Counter()
    errors = []
    for row in rows:
        for stem in row["paths"]:
            result = json.loads((data_root / "analysis" / row["track_id"] / f"{stem}.json").read_text())
            data = by_stem.setdefault(stem, {"key_correct": 0, "count": 0, "bpm_errors": [], "major_correct": 0, "minor_correct": 0})
            data["count"] += 1
            correct = result["key"] == row["key"]
            data["key_correct"] += correct
            data["minor_correct" if row["minor"] else "major_correct"] += correct
            if result["bpm"]:
                data["bpm_errors"].append(abs(result["bpm"] - row["bpm"]))
            if stem == "mix" and not correct:
                confusion[(row["key"], result["key"])] += 1
            if stem == "mix" and result["bpm"] and abs(result["bpm"] - row["bpm"]) > 3:
                errors.append((row["seed"], row["bpm"], result["bpm"]))
    print(json.dumps({"stems": {name: {**{k:v for k,v in value.items() if k != "bpm_errors"},
                                                     "mean_bpm_error": float(np.mean(value["bpm_errors"]))} for name,value in by_stem.items()},
                      "confusion": confusion.most_common(12), "tempo_errors": errors}, indent=2))


if __name__ == "__main__":
    main()

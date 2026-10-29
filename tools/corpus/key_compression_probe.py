"""Evaluate generic chroma compression on disjoint synthetic seed splits."""
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from remixer.cpu.analyze import estimate_key


def main():
    from remixer.config import data_dir
    data_root = data_dir()
    rows = pq.read_table(data_root / "corpus/manifest.parquet").to_pylist()
    counts = {power: {"train": [0, 0], "held_out": [0, 0]} for power in (.2, .25, .4, .5, .75, 1)}
    for row in rows:
        features = json.loads((data_root / "analysis" / row["track_id"] / "mix.json").read_text())
        chroma = np.sum([window["chroma"] for window in features["windows"]], axis=0)
        for power, splits in counts.items():
            split = splits["train" if row["seed"] < 300 else "held_out"]
            split[0] += estimate_key(chroma**power)[0] == row["key"]
            split[1] += 1
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()

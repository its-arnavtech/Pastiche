"""Parallelize independent compatible bass upgrades behind the summary pass."""
from __future__ import annotations

import json
from pathlib import Path


def upgrade(row):
    from remixer.config import data_dir
    from remixer.corpus.generate import atomic_json
    from remixer.cpu.analyze import VERSION, upgrade_tempo, with_provenance
    path = data_dir() / "analysis" / row["track_id"] / "bass.json"
    features = json.loads(path.read_text())
    if features["version"] == VERSION:
        return 0
    features = upgrade_tempo(Path(row["paths"]["bass"]), features)
    features = with_provenance(features, {name: row.get(name) for name in ("synthetic", "augmented", "real")})
    atomic_json(path, features)
    return 1


def main():
    import pyarrow.parquet as pq
    from remixer.config import data_dir
    from remixer.cpu.runtime import process_pool
    rows = pq.read_table(data_dir() / "corpus/manifest.parquet").to_pylist()
    # One existing summary/refinement process is also active. Fifteen workers
    # plus that process fit the sixteen-worker CPU budget with an Intel host.
    with process_pool(15) as pool:
        completed = sum(pool.map(upgrade, rows))
    print(json.dumps({"upgraded_bass_files": completed}))


if __name__ == "__main__":
    main()

"""Validate new seeded arrangements after the full-budget peak sequence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time


def main():
    data = Path(os.environ.get("REMIXER_DATA_DIR", "data"))
    while True:
        state_path = data / "cpu-peak/runner.json"
        if state_path.exists() and json.loads(state_path.read_text())["phase"] == "complete":
            break
        time.sleep(5)
    from remixer.corpus.generate import generate_corpus
    from remixer.cpu.analyze import analyze_corpus
    generate_corpus(data / "corpus-varied", n=24, seed=500, varied=True)
    result = analyze_corpus(data / "corpus-varied", data / "analysis-varied")
    print(json.dumps({key: value for key, value in result.items() if key not in {"scores", "sample_series"}}, indent=2))


if __name__ == "__main__":
    main()

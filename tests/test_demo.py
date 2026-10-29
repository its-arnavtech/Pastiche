"""remixer demo --fast runs the whole product loop (GPU stages replaced by stubs) and every check passes."""
import json

import pytest

pytest.importorskip("hnswlib")


@pytest.mark.slow
def test_fast_demo_passes_every_check(tmp_path_factory):
    from remixer.demo import Demo

    out = tmp_path_factory.mktemp("demo")             # short path: the section cache has long file names on Windows
    assert Demo(out, n_tracks=12, duration_s=24.0, fast=True).run() == 0
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["failed"] == 0 and len(summary["checks"]) >= 25
    assert {"a burst of 3 presses is ONE skip (one burst, three presses)",
            "only the affected sections were re-rendered; every other section hash and its audio is unchanged"} <= \
        {c["check"] for c in summary["checks"] if c["ok"]}
    assert (out / "demo.log").exists() and list((out / "audio").glob("*.flac"))

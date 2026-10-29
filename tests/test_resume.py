"""A worker killed after finishing a unit but before its catalog write must not lose that unit on resume.

Found by `remixer demo` (forced kill of the separation worker): the restart saw the finished stem files, acked the
job as cached, and never registered the stems, so the track silently had no stem rows. Same shape in the embedder.
"""
import copy
import os
from types import SimpleNamespace

import numpy as np
import pytest

from remixer.adapters import build
from remixer.config import DEFAULT_PROFILE, Profile, compute_resources

pytest.importorskip("torch")


@pytest.fixture
def tenant(tmp_path):
    a = build(Profile(raw=copy.deepcopy(DEFAULT_PROFILE), resources=compute_resources({}), data_dir=tmp_path / "data"))
    yield a
    a.catalog.close()
    a.jobs.close()


def test_separation_registers_finished_stems_after_a_kill(tenant):
    from remixer.gpu.separate import Separator

    sources = ("drums", "bass", "vocals", "other")
    sep = object.__new__(Separator)
    sep.a, sep._leased = tenant, {}
    sep.stems_root = tenant.profile.data_dir / "stems"
    sep.runner = SimpleNamespace(version="demucs@test", name="htdemucs", sources=sources, sr=44100)
    tid = "t" * 64
    tenant.catalog.upsert("tracks", {"track_id": tid, "synthetic": 1}, key=["track_id"])
    final = sep.stems_root / tid[:2] / tid / "demucs_test"
    final.mkdir(parents=True)
    for s in sources:                                    # the dead worker had renamed every stem into place
        (final / f"{s}.wav").write_bytes(b"RIFF")
    tenant.jobs.enqueue("separate:htdemucs", tid, {"track_id": tid, "path": "x"})
    job = tenant.jobs.lease("separate:htdemucs", "w")[0]
    sep._leased[job.id] = job

    loaded = SimpleNamespace(item=job, frames=44100 * 30)
    assert sep._new_state(loaded, persist=True) is None   # nothing to separate
    rows = tenant.catalog.query("SELECT stem_name, synthetic, duration_s FROM stems WHERE track_id=?", (tid,))
    assert sorted(r["stem_name"] for r in rows) == sorted(sources) and all(r["synthetic"] == 1 for r in rows)
    assert tenant.jobs.counts()["done"] == 1


def test_stale_partial_files_of_dead_workers_are_swept(tenant):
    from remixer.gpu.separate import Separator

    sep = object.__new__(Separator)
    sep.stems_root = tenant.profile.data_dir / "stems"
    d = sep.stems_root / "ab" / "track" / "v"
    d.mkdir(parents=True)
    dead = d / "bass.99999999.partial.wav"
    alive = d / f"bass.{os.getpid()}.partial.wav"
    final = d / "bass.wav"
    for p in (dead, alive, final):
        p.write_bytes(b"x")
    assert sep.sweep_partials() == 1
    assert not dead.exists() and alive.exists() and final.exists()


def test_embedder_registers_saved_vectors_after_a_kill(tenant):
    from remixer.gpu.embed import Embedder, StemState

    emb = object.__new__(Embedder)
    emb.a, emb.name, emb.version, emb.dim, emb._leased = tenant, "clap-test", "clap-test@v1", 8, {}
    emb.vec_root = tenant.profile.data_dir / "embeddings" / "clap-test_v1"
    emb.vec_root.mkdir(parents=True)
    vecs = np.random.default_rng(0).normal(size=(3, 8)).astype(np.float16)
    np.save(emb.vec_root / "s1.npy", vecs)                # saved by the dead worker, never registered
    st = StemState(item={"stem_id": "s1"}, stem_id="s1", windows=[(0, 5000), (5000, 10000), (10000, 12000)], synthetic=True)
    emb._finish({"stem_id": "s1"}, st, cached=True)
    rows = tenant.catalog.query("SELECT owner_kind FROM embeddings WHERE model_version='clap-test@v1'")
    assert sorted(r["owner_kind"] for r in rows) == ["stem", "window", "window", "window"]
    assert tenant.catalog.query("SELECT COUNT(*) AS n FROM windows")[0]["n"] == 3
    emb._finish({"stem_id": "s1"}, st, cached=True)       # a second resume is a no-op, not a duplicate-key error
    assert tenant.catalog.query("SELECT COUNT(*) AS n FROM embeddings")[0]["n"] == 4

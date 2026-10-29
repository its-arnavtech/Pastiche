import hashlib
import os
import stat

import pytest


def test_put_is_content_addressed_and_idempotent(adapters):
    b = adapters.blobs
    k1 = b.put(b"stem bytes", namespace="stems", suffix=".flac")
    assert b.put(b"stem bytes", namespace="stems", suffix=".flac") == k1
    assert hashlib.sha256(b"stem bytes").hexdigest() in k1
    assert k1.startswith("stems/") and k1.endswith(".flac")
    assert b.put(b"other bytes", namespace="stems", suffix=".flac") != k1
    assert b.get(k1) == b"stem bytes"
    assert b.exists(k1)


def test_namespaces_do_not_collide(adapters):
    b = adapters.blobs
    assert b.put(b"x", namespace="stems") != b.put(b"x", namespace="renders")


def test_delete(adapters):
    b = adapters.blobs
    k = b.put(b"gone soon")
    b.delete(k)
    assert not b.exists(k)
    b.delete(k)  # deleting twice is fine
    with pytest.raises(Exception):
        b.get(k)


def test_put_file_copies_and_never_touches_the_source(adapters, tmp_path):
    src = tmp_path / "library" / "song.wav"
    src.parent.mkdir()
    src.write_bytes(b"RIFF....user audio")
    os.chmod(src, stat.S_IRUSR)  # the user's library is read-only
    before = (src.stat().st_mtime_ns, src.read_bytes())
    try:
        k = adapters.blobs.put_file(src, namespace="sources")
        assert adapters.blobs.get(k) == b"RIFF....user audio"
        assert k.endswith(".wav")
        assert k == adapters.blobs.put(b"RIFF....user audio", namespace="sources", suffix=".wav")
        assert src.exists() and (src.stat().st_mtime_ns, src.read_bytes()) == before
    finally:
        os.chmod(src, stat.S_IRUSR | stat.S_IWUSR)


def test_path_is_readable_or_none(adapters):
    k = adapters.blobs.put(b"mmap me")
    p = adapters.blobs.path(k)
    assert p is None or open(p, "rb").read() == b"mmap me"


def test_durable_across_reopen(open_tenant):
    k = open_tenant("tenant-a").blobs.put(b"durable")
    assert open_tenant("tenant-a").blobs.get(k) == b"durable"

import numpy as np
import pytest

pytest.importorskip("hnswlib")

DIM = 16


def unit(n, seed=0):
    v = np.random.default_rng(seed).normal(size=(n, DIM)).astype(np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def test_nearest_neighbour_of_a_stored_vector_is_itself(adapters):
    idx = adapters.vector_index("windows", DIM)
    vecs = unit(200)
    ids = list(range(1000, 1200))
    idx.add(ids, vecs)
    assert len(idx) == 200
    labels, dist = idx.search(vecs[:20], k=5)
    assert labels.shape == dist.shape == (20, 5)
    assert labels[:, 0].tolist() == ids[:20]
    assert np.all(dist[:, 0] <= dist[:, 1] + 1e-6)
    assert np.allclose(dist[:, 0], 0, atol=1e-4)


def test_k_is_clipped_and_empty_index_returns_no_columns(adapters):
    idx = adapters.vector_index("stems", DIM)
    labels, dist = idx.search(unit(3), k=4)
    assert labels.shape == dist.shape == (3, 0)
    idx.add([1, 2], unit(2, seed=1))
    labels, _ = idx.search(unit(1), k=10)
    assert labels.shape == (1, 2) and sorted(labels[0].tolist()) == [1, 2]


def test_save_and_reopen(open_tenant):
    idx = open_tenant("tenant-a").vector_index("stems", DIM)
    vecs = unit(30, seed=2)
    idx.add(list(range(30)), vecs)
    idx.save()
    again = open_tenant("tenant-a").vector_index("stems", DIM)
    assert len(again) == 30
    assert again.search(vecs[7:8], k=1)[0][0, 0] == 7


def test_named_indexes_are_separate(adapters):
    a = adapters.vector_index("stems", DIM)
    a.add([1], unit(1))
    a.save()
    assert len(adapters.vector_index("windows", DIM)) == 0

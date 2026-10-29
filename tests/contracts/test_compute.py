"""ComputeBackend: discovery only. No GPU is assumed; plain CI has none."""


def test_devices_always_include_a_cpu(adapters):
    devs = adapters.compute.devices()
    assert any(d.kind == "cpu" for d in devs)
    assert all(d.kind in {"cpu", "cuda", "npu", "igpu"} for d in devs)
    assert all(d.total_memory >= d.free_memory >= 0 for d in devs if d.total_memory)


def test_worker_budgets_are_positive(adapters):
    c = adapters.compute
    assert c.cpu_workers("cpu") >= 1
    assert c.cpu_workers("gpu") >= 1
    assert isinstance(c.free_vram(), int) and c.free_vram() >= 0

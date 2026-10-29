import numpy as np
import pytest

from remixer.npu.scorer import OpenVINOScorer, ScorerSpec, export_scorer, reference_score


def test_static_ir_cpu_matches_numpy_and_missing_device_falls_back(tmp_path):
    spec = ScorerSpec(features=16, hidden=8, batch=4, seed=22)
    model = export_scorer(tmp_path, spec)
    scorer = OpenVINOScorer(model, spec, device="MISSING_DEVICE")
    assert scorer.device == "CPU"
    assert scorer.fallback_reason
    inputs = np.random.default_rng(1).normal(size=(4, 16)).astype(np.float32)
    np.testing.assert_allclose(scorer.score(inputs), reference_score(inputs, spec), atol=.001)
    with pytest.raises(ValueError, match="shape"):
        scorer.score(inputs[:1])


def test_nvidia_device_is_excluded_before_compilation(tmp_path):
    import openvino as ov
    core = ov.Core()
    spec = ScorerSpec(features=16, hidden=8, batch=4)
    model = export_scorer(tmp_path, spec)
    class GuardedCore:
        def __init__(self):
            self.compiled_devices = []
        def get_property(self, device, name):
            return "NVIDIA GeForce" if device == "GPU.1" else core.get_property(device, name)
        def compile_model(self, model, device, config):
            self.compiled_devices.append(device)
            assert device != "GPU.1"
            return core.compile_model(model, device, config)
    fake = GuardedCore()
    scorer = OpenVINOScorer(model, spec, "GPU.1", fake)
    assert scorer.device == "CPU"
    assert "not Intel" in scorer.fallback_reason
    assert fake.compiled_devices == ["CPU"]

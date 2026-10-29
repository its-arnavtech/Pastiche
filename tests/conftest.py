import pytest


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("REMIXER_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"

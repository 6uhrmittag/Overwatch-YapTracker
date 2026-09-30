import pytest


@pytest.fixture(autouse=True)
def _isolated_data_dir(monkeypatch, tmp_path):
    """No test may read or write the real data folder (config, logs, database)."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))

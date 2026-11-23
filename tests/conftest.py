import pytest


@pytest.fixture(autouse=True)
def _isolated_data_dir(monkeypatch, tmp_path):
    """No test may read or write the real data folder (config, logs, database)."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    from yaptracker import config

    config.forget()  # config.json is kept in memory (#451); each test starts from its own file


@pytest.fixture(autouse=True)
def _no_openrouter_model_list(monkeypatch):
    """No test asks OpenRouter for its model list (#584): it's offline here."""
    from yaptracker import ai_models

    def offline():
        raise OSError("no network in tests")

    monkeypatch.setattr(ai_models, "fetch_list", offline)

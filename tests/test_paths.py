import sys

from yaptracker import __main__ as entry
from yaptracker import paths


def test_data_dir_follows_xdg_on_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.data_dir() == tmp_path / "yaptracker"


def test_data_dir_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert paths.data_dir() == tmp_path / "YapTracker" / "data"


def test_windowed_exe_logs_to_file(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    entry._log_to_file_without_console()
    print("hello from a windowed exe")
    sys.stdout.close()
    assert "hello from a windowed exe" in paths.log_file().read_text(encoding="utf-8")

"""The app log (#98): rotates, and the windowed exe's stdout/stderr land in it."""

import logging
import sys

import pytest

from yaptracker import logs, paths


@pytest.fixture
def data(monkeypatch, tmp_path):
    """A fresh data folder; whatever setup() adds to the root logger is removed again."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "linux")
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield paths.log_file()
    for handler in root.handlers[:]:
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)


def test_windowed_exe_prints_and_tracebacks_land_in_the_log(data, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    logs.setup(argv=["YapTracker.exe"])
    print("hello from a windowed exe")
    sys.stderr.write("Traceback (most recent call last):\n  oops\n")
    logging.getLogger("yaptracker.capture").info("capturing window 42")
    text = data.read_text(encoding="utf-8")
    assert "INFO stdout: hello from a windowed exe" in text
    assert "WARNING stderr: Traceback (most recent call last):" in text
    assert "INFO yaptracker.capture: capturing window 42" in text


def test_the_log_never_grows_beyond_five_files(data, monkeypatch):
    monkeypatch.setattr(logs, "MAX_BYTES", 2_000)
    logs.setup(argv=["YapTracker.exe"])
    for n in range(2_000):
        logging.getLogger("yaptracker").info("line %d of a long evening", n)
    files = sorted(p.name for p in data.parent.iterdir())
    assert files == ["yaptracker.log"] + [f"yaptracker.log.{n}" for n in range(1, 5)]
    assert "line 1999" in data.read_text(encoding="utf-8")


def test_the_window_process_keeps_its_own_small_log(data, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    before = logging.getLogger().handlers[:]
    logs.setup(argv=["YapTracker.exe", "--multiprocessing-fork", "parent_pid=1"])
    assert logging.getLogger().handlers == before  # never touches yaptracker.log
    print("pywebview says hi")
    sys.stdout.close()
    assert "pywebview says hi" in (data.parent / "window.log").read_text(encoding="utf-8")


def test_partial_writes_become_one_line():
    lines = []

    class Collect(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    logger = logging.getLogger("test-to-log")
    logger.addHandler(Collect())
    logger.propagate = False
    logger.setLevel(logging.INFO)
    stream = logs.ToLog(logger, logging.INFO)
    for part in ("hel", "lo\nwor", "ld\n", "\n"):
        stream.write(part)
    assert lines == ["hello", "world"]


def test_open_logs_is_windows_only(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert not logs.folder_opens()
    monkeypatch.setattr(sys, "platform", "win32")
    assert logs.folder_opens()

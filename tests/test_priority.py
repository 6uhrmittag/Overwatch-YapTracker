"""Who runs in Windows' efficiency mode (#563): the child processes, and the main process only
when it reads the chat itself."""

import threading

from yaptracker import config, priority
from yaptracker.__main__ import in_efficiency_mode
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.reader import ChatReader
from yaptracker.store.repo import Store

CHILD = ["YapTracker.exe", "--multiprocessing-fork", "parent_pid=1", "pipe_handle=2"]


def test_the_main_process_leaves_efficiency_mode_when_the_reader_has_its_own_process():
    assert config.ocr_own_process()  # the default
    assert not in_efficiency_mode(["YapTracker.exe", "--background"])
    assert in_efficiency_mode(CHILD)  # the window's process, the reader's process


def test_reading_in_the_main_process_keeps_it_in_efficiency_mode(tmp_path, monkeypatch):
    from yaptracker import paths

    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text('{"ocr_own_process": false}', encoding="utf-8")
    config.forget()
    assert not config.ocr_own_process()
    assert in_efficiency_mode(["YapTracker.exe"])


def test_the_reader_thread_is_only_lowered_when_it_does_the_ocr_itself(tmp_path, monkeypatch):
    lowered = []
    monkeypatch.setattr(priority, "lower_this_thread",
                        lambda: lowered.append(threading.current_thread().name))  # fmt: skip
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        for lowest in (True, False):
            reader = ChatReader(lambda image: [], store, MatchTracker(store, Pause()),
                                lowest=lowest)  # fmt: skip
            reader.start()
            reader.stop()
        assert len(lowered) == 1
    finally:
        store.close()

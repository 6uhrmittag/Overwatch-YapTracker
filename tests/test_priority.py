"""Who runs in Windows' efficiency mode (#563): the child processes, and the main process only
when it reads the chat itself."""

import threading

from yaptracker import config, priority
from yaptracker.__main__ import reader_has_its_own_process
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.reader import ChatReader
from yaptracker.store.repo import Store


def test_the_reader_has_its_own_process_unless_dev_or_config_says_no():
    from yaptracker import paths

    assert reader_has_its_own_process(dev=False)  # no config yet: the default
    assert not reader_has_its_own_process(dev=True)  # app.py makes no child in --dev
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text('{"ocr_own_process": false}', encoding="utf-8")
    assert not reader_has_its_own_process(dev=False)
    paths.config_file().write_text("{broken", encoding="utf-8")
    assert reader_has_its_own_process(dev=False)
    assert paths.config_file().read_text(encoding="utf-8") == "{broken"  # left alone


def test_the_main_process_agrees_with_the_app_about_the_child():
    """One rule in two places (the entry point can't import the app): they must not drift."""
    assert config.ocr_own_process() is reader_has_its_own_process(dev=False)


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

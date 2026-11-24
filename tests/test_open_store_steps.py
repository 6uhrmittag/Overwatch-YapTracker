"""App start-up and shutdown of the store in named steps (#311): the order that
matters, and a newer database left alone. Fakes, no game."""

from types import SimpleNamespace

from yaptracker import app, runtime
from yaptracker.store import repo
from yaptracker.store.db import NewerDatabaseError


def test_the_store_closes_last_after_everything_that_writes_to_it(monkeypatch):
    stopped = []

    def part(name):
        return SimpleNamespace(
            stop=lambda: stopped.append(name), close=lambda: stopped.append(name)
        )

    for name in ("backups", "ocr_child", "reader", "read_again", "health", "matches", "store"):
        monkeypatch.setattr(runtime, name, part(name))
    monkeypatch.setattr(runtime, "read_again", None)  # not started: skipped, nothing fails
    app._close_store()
    # the OCR child before the reader (#563): its last read doesn't wait behind a starved child
    assert stopped == ["backups", "ocr_child", "reader", "health", "matches", "store"]


def test_the_ocr_process_is_on_unless_config_says_false():
    from yaptracker import config, paths

    assert config.ocr_own_process()
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    for written, on in (('{"ocr_own_process": false}', False), ('{"ocr_own_process": true}', True),
                        ("{}", True)):  # fmt: skip
        paths.config_file().write_text(written, encoding="utf-8")
        config.forget()
        assert config.ocr_own_process() is on


def test_a_newer_database_is_said_and_left_alone(monkeypatch):
    def newer():
        raise NewerDatabaseError("written by YapTracker 9.9")

    monkeypatch.setattr(repo.Store, "open", staticmethod(newer))
    monkeypatch.setattr(runtime, "store", None)
    monkeypatch.setattr(runtime, "data_too_new", None)
    assert app._open_database() is False
    assert runtime.store is None and runtime.data_too_new == "written by YapTracker 9.9"

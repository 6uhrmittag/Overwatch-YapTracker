"""App start-up and shutdown of the store in named steps (#311), and the auto-translate look in
its steps: the order that matters, and a newer database left alone. Fakes, no game."""

from types import SimpleNamespace

from yaptracker import app, runtime
from yaptracker.auto_translate import _to_send
from yaptracker.store import repo
from yaptracker.store.db import NewerDatabaseError


def test_the_store_closes_last_after_everything_that_writes_to_it(monkeypatch):
    stopped = []

    def part(name):
        return SimpleNamespace(
            stop=lambda: stopped.append(name), close=lambda: stopped.append(name)
        )

    for name in ("backups", "reader", "read_again", "health", "matches", "store"):
        monkeypatch.setattr(runtime, name, part(name))
    monkeypatch.setattr(runtime, "read_again", None)  # not started: skipped, nothing fails
    app._close_store()
    assert stopped == ["backups", "reader", "health", "matches", "store"]


def test_a_newer_database_is_said_and_left_alone(monkeypatch):
    def newer():
        raise NewerDatabaseError("written by YapTracker 9.9")

    monkeypatch.setattr(repo.Store, "open", staticmethod(newer))
    monkeypatch.setattr(runtime, "store", None)
    monkeypatch.setattr(runtime, "data_too_new", None)
    assert app._open_database() is False
    assert runtime.store is None and runtime.data_too_new == "written by YapTracker 9.9"


def test_only_lines_worth_a_look_go_to_the_translator():
    def line(text, **more):
        fields = {"channel": "match", "hero": None, "role": None, "translation": None,
                  "translation_from": None, "text": text} | more  # fmt: skip
        return SimpleNamespace(**fields)

    lines = [line("que pasa con el tanque"), line("gg ez"), line("merci", role="me"),
             line("Zappy started playing Overwatch.", channel="system"),
             line("que tal amigos", translation_from="ES")]  # fmt: skip
    assert _to_send(lines, {"EN", "DE"}) == [lines[0]]

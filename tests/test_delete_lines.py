"""Delete a wrong or doubled chat line (#227): soft delete, hidden everywhere, Undo, and dedup
doesn't bring it back while it's still on screen."""

import sqlite3
import time

import numpy as np
import pytest
from nicegui.testing import User, user_simulation
from nicegui.testing.user_interaction import UserInteraction

from yaptracker import config, runtime
from yaptracker.capture.source import Region
from yaptracker.matches import MatchTracker
from yaptracker.ocr.engine import OcrLine
from yaptracker.pause import Pause
from yaptracker.reader import ChatReader
from yaptracker.store import db, schema
from yaptracker.store.repo import Store
from yaptracker.ui import shell

NOW = time.time()


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def evening(store):
    session = store.start_session(NOW - 100)
    match = store.start_match(session, NOW - 90, "heroselect")
    pid = store.add_player("Pickle", NOW - 80)
    keep = store.add_message(ts=NOW - 80, channel="match", speaker_raw="Pickle", player_id=pid,
                             text="wahoo team", match_id=match)  # fmt: skip
    doubled = store.add_message(ts=NOW - 79, channel="match", speaker_raw="Pickle", player_id=pid,
                                text="wahoo team", match_id=match)  # fmt: skip
    return session, match, pid, keep, doubled


def test_a_deleted_line_is_gone_everywhere_and_comes_back_with_undo(store):
    session, match, pid, keep, doubled = evening(store)
    store.delete_message(doubled, NOW)
    assert [m.id for m in store.messages(match)] == [keep]
    assert [m.id for m in store.player_messages(pid)] == [keep]
    assert store.player(pid).yaps == 1
    assert store.met_before(pid, None)[1] == 1  # the familiar-face card counts it once
    assert [m.id for m in store.search("wahoo")] == [keep]
    assert store.sessions()[0].yaps == 1 and store.session_matches(session)[0].yaps == 1
    store.restore_message(doubled)
    assert [m.id for m in store.messages(match)] == [keep, doubled]
    assert store.player(pid).yaps == 2


def test_the_migration_keeps_every_line_and_backs_up_first(tmp_path, monkeypatch):
    path, backups = tmp_path / "yaptracker.db", tmp_path / "backups"
    with monkeypatch.context() as v3_app:  # what's on Marv's and Void's PCs before #227
        v3_app.setattr(db, "MIGRATIONS", schema.MIGRATIONS[:3])
        v3_app.setattr(db, "LATEST", 3)
        old = db.connect(path, backups)
        old.execute("INSERT INTO chat_messages (ts, channel, text) VALUES (1.0, 'match', 'gg')")
        old.close()
    store = Store.open(path, backups)
    try:
        assert [m.text for m in store.search("gg")] == ["gg"]
    finally:
        store.close()
    (copy,) = backups.iterdir()
    with sqlite3.connect(copy) as before:
        assert before.execute("SELECT version FROM schema_version").fetchone() == (3,)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_dedup_doesnt_bring_back_a_deleted_line_while_its_on_screen(store):
    frames = [np.zeros((395, 615, 3), np.uint8) for _ in range(3)]
    line = [OcrLine("[Pickle]: wahoo team", 0.99, Region(64, 300, 300, 24))]
    clock = Clock()
    tracker = MatchTracker(store, Pause(), clock=clock)
    tracker.capture_alive(clock.now)
    reader = ChatReader(lambda image: line, store, tracker, clock=clock)
    reader.read_frame(clock.now, frames[0])
    (stored,) = store.messages(tracker.match_id)
    store.delete_message(stored.id, clock.now)
    for frame in frames[1:]:  # still in the chat box: read again and again
        clock.now += 1.5
        reader.read_frame(clock.now, frame)
    assert store.messages(tracker.match_id) == []


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_delete_in_live_with_undo(user: User, store, monkeypatch):
    config.save_setup_state("done")
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(NOW)
    tracker.new_match()
    first = store.add_message(ts=NOW, channel="match", speaker_raw="Pickle", text="wahoo team",
                              match_id=tracker.match_id)  # fmt: skip
    store.add_message(ts=NOW + 1, channel="match", speaker_raw="Pickle", text="wahoo team",
                      match_id=tracker.match_id)  # fmt: skip
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "matches", tracker)
    await user.open("/")
    await user.should_see("2 yaps")
    buttons = list(user.find(marker="delete-line").elements)
    assert len(buttons) == 2  # one on each line
    UserInteraction(user, {buttons[0]}, None).click()
    assert [m.id for m in store.messages(tracker.match_id)] != [first, first + 1]
    assert len(store.messages(tracker.match_id)) == 1
    await user.should_see("Line deleted")
    await user.should_see("1 yap")
    user.find(marker="undo").click()
    assert len(store.messages(tracker.match_id)) == 2

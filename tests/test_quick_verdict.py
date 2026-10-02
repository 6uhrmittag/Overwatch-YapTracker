"""Quick verdicts (#220): one click in the Yappers list and from a name in the chat, with undo."""

import time

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.store.repo import Store
from yaptracker.ui import shell

NOW = time.time()


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


@pytest.fixture
def store(tmp_path, monkeypatch):
    config.save_setup_state("done")
    config.save_identity(["Me4ever"], ["Waffle"])
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    tracker = MatchTracker(s, Pause())
    tracker.capture_alive(NOW)
    tracker.new_match()
    for name in ("Pickle", "Waffle", "Me4ever"):
        pid = s.add_player(name, NOW)
        role = {"Waffle": "crew", "Me4ever": "me"}.get(name)
        s.add_message(ts=NOW, channel="match", text=f"hi from {name}", match_id=tracker.match_id,
                      speaker_raw=name, player_id=pid, role=role)  # fmt: skip
    monkeypatch.setattr(runtime, "store", s)
    monkeypatch.setattr(runtime, "matches", tracker)
    yield s
    s.close()


async def test_one_click_in_the_list_sets_it_and_undo_takes_it_back(user: User, store):
    await user.open("/")
    user.find(marker="nav-yappers").click()
    await user.should_see("Pickle")
    user.find(marker="quick-fun").click()  # only Pickle's row has them: not you, not crew
    assert store.player(1).verdict == "fun"
    await user.should_see("Pickle: Fun")
    user.find(marker="undo").click()
    assert store.player(1).verdict is None
    user.find(marker="quick-avoid").click()
    user.find(marker="quick-avoid").click()  # the current one again: cleared
    assert store.player(1).verdict is None
    await user.should_see("Pickle: no verdict yet")


async def test_a_name_in_live_opens_verdict_note_and_profile(user: User, store):
    await user.open("/")
    await user.should_see("hi from Pickle")
    user.find(content="Pickle:").click()
    await user.should_see("Quick note, Enter saves")
    user.find(marker="quick-friend").click()
    assert store.player(1).verdict == "friend"
    note = user.find(marker="who-note")
    note.type("the Lúcio from Tuesday")
    note.trigger("keydown.enter")
    assert store.player(1).notes == "the Lúcio from Tuesday"
    note.type("said gg first")
    note.trigger("keydown.enter")
    assert store.player(1).notes == "the Lúcio from Tuesday\nsaid gg first"  # appended
    await user.should_see("Note added for Pickle")
    user.find(marker="undo").click()
    assert store.player(1).notes == "the Lúcio from Tuesday"
    user.find(marker="who-profile").click()
    await user.should_see("Your verdict")


async def test_you_and_crew_get_no_menu(user: User, store):
    await user.open("/")
    await user.should_see("hi from Waffle")
    user.find(content="Waffle:").click()
    user.find(content="you:").click()
    await user.should_not_see("Quick note, Enter saves")

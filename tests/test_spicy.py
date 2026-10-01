"""Spicy yaps (#77): flagged lines, a heads-up when that player is back, never a verdict."""

import time

import numpy as np
import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.capture.source import Region
from yaptracker.familiar import FamiliarFaces
from yaptracker.matches import MatchTracker
from yaptracker.ocr.engine import OcrLine
from yaptracker.pause import Pause
from yaptracker.reader import ChatReader
from yaptracker.store.repo import Store
from yaptracker.ui import shell


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    monkeypatch.setattr(runtime, "store", s)
    yield s
    s.close()


@pytest.fixture
async def user():
    config.save_setup_state("done")
    async with user_simulation(root=shell.root) as user:
        yield user


def spicy_player(store, flagged=2):
    """gremlin.exe, met in an earlier match, with `flagged` spicy lines; returns (id, new match)."""
    session = store.start_session(time.time() - 3600)
    pid = store.add_player("gremlin.exe", time.time() - 3600)
    match = store.start_match(session, time.time() - 3600, "gap")
    for n in range(3):
        store.add_message(ts=time.time() - 3600 + n, channel="match", text=f"line {n}",
                          match_id=match, speaker_raw="gremlin.exe", player_id=pid,
                          flagged="overwatch" if n < flagged else None)  # fmt: skip
    return pid, store.start_match(session, time.time(), "heroselect")


def test_overwatchs_report_link_flags_the_line(store):
    image = np.zeros((80, 615, 3), np.uint8)
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(1000.0)
    reader = ChatReader(lambda img: [OcrLine("[gremlin.exe]: ez noobs [Report]", 0.99,
                                             Region(64, 10, 400, 24))], store, tracker)  # fmt: skip
    reader.read_frame(1000.0, image)
    (message,) = store.messages(tracker.match_id)
    assert (message.text, message.flagged) == ("ez noobs", "overwatch")


async def test_mark_a_line_as_spicy_and_take_it_back(user: User, store, monkeypatch):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive()
    tracker.chat_changed()
    message = store.add_message(ts=time.time(), channel="match", text="you all suck",
                                match_id=tracker.match_id, speaker_raw="x")  # fmt: skip
    monkeypatch.setattr(runtime, "matches", tracker)
    await user.open("/")
    await user.should_see("you all suck")
    user.find(marker="chat-line").click()
    user.find(marker="spicy-toggle").click()
    assert store.message(message).flagged == "manual"
    await user.should_see('class="yt-spicy"')  # the chili on the line
    user.find(marker="chat-line").click()
    await user.should_see("Not spicy")
    user.find(marker="spicy-toggle").click()
    assert store.message(message).flagged is None


async def test_profile_and_yappers_know_who_was_spicy(user: User, store):
    spicy_player(store)
    store.add_player("NoodleBonk", time.time())
    await user.open("/")
    user.find(marker="nav-yappers").click()
    user.find(marker="filter-spicy").click()
    await user.should_see("gremlin.exe")
    await user.should_not_see("NoodleBonk")
    user.find(marker="yapper-1").click()
    await user.should_see("2 spicy yaps: flagged by Overwatch or by you.")


async def test_the_card_gives_a_heads_up_and_only_suggests_nope(user: User, store, monkeypatch):
    pid, now = spicy_player(store)
    faces = FamiliarFaces(store)
    faces.heard(pid, now)
    monkeypatch.setattr(runtime, "familiar", faces)
    await user.open("/")
    await user.should_see("Heads-up: last time 2 spicy yaps")
    assert store.player(pid).verdict is None  # never set by itself
    user.find(marker="face-nope").click()
    assert store.player(pid).verdict == "avoid"

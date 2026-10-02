"""Callouts in Live and transcripts (#185): dimmed, with the hero, repeats counted not repeated."""

import time

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.store.repo import Store
from yaptracker.ui import shell


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    monkeypatch.setattr(runtime, "store", s)
    yield s
    s.close()


def spam(store, match, now):
    lines = [("Enemy Sombra!", "Kiriko")] * 4 + [("gl hf", None), ("Enemy Sombra!", "Kiriko")]
    for n, (text, hero) in enumerate(lines):
        store.add_message(ts=now + n, channel="team", text=text, speaker_raw="Pickle", hero=hero,
                          match_id=match)  # fmt: skip


def rows(user):
    return [row for row in user.find(marker="chat-line").elements]


async def test_transcript_counts_repeated_callouts(user: User, store):
    config.save_setup_state("done")
    now = time.time()
    session = store.start_session(now - 600)
    match = store.start_match(session, now - 600, "heroselect")
    spam(store, match, now - 500)
    await user.open("/")
    user.find(marker="nav-sessions").click()
    user.find(marker=f"session-{session}").click()
    user.find(marker=f"match-{match}").click()
    await user.should_see("· as Kiriko")
    await user.should_see("×4")
    lines = sorted(rows(user), key=lambda e: e.id)
    assert len(lines) == 3  # 4x "Enemy Sombra!", "gl hf", "Enemy Sombra!" again after it
    assert ["yt-line--callout" in r.classes for r in lines] == [True, False, True]


async def test_live_counts_them_as_they_come(user: User, store, monkeypatch):
    config.save_setup_state("done")
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(time.time())
    tracker.new_match(time.time(), source="heroselect")
    monkeypatch.setattr(runtime, "matches", tracker)
    spam(store, tracker.match_id, time.time())
    await user.open("/")
    await user.should_see("×4")
    await user.should_see("1 yap")  # callouts aren't yaps (#182)
    assert len(rows(user)) == 3

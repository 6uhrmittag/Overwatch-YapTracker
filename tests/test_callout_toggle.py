"""Callouts hidden in Live and transcripts by default (#289): a switch with a count, the choice
remembered. Hidden rows stay in the page (presence and repeats keep working, #182, #185)."""

import time

import pytest
from nicegui.testing import User, user_simulation

from tests.test_sessions import evening
from yaptracker import config, runtime
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
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
    async with user_simulation(root=shell.root) as user:
        yield user


def hidden(user: User, marker: str) -> bool:
    (feed,) = user.find(marker=marker).elements
    return "yt-hide-callouts" in feed.classes


async def test_live_hides_callouts_until_switched_on_and_remembers(user: User, store, monkeypatch):
    config.save_setup_state("done")
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive()
    tracker.chat_changed()
    now = time.time()
    store.add_message(ts=now, channel="match", text="gg", speaker_raw="Pickle",
                      match_id=tracker.match_id)  # fmt: skip
    for n, said in enumerate(["Group up! ◇", "Enemy Sombra!"]):
        store.add_message(ts=now + n, channel="team", text=said, speaker_raw="Bo", hero="Ana",
                          match_id=tracker.match_id)  # fmt: skip
    monkeypatch.setattr(runtime, "matches", tracker)
    await user.open("/")
    await user.should_see("gg")
    await user.should_see("+2 callouts")
    assert hidden(user, "lines")
    user.find(marker="callouts-switch").click()
    assert not hidden(user, "lines") and config.show_callouts()
    await user.should_not_see("+2 callouts")


async def test_transcripts_follow_the_same_choice(user: User, store):
    config.save_setup_state("done")
    session, first, second = evening(store)
    store.add_message(ts=store.session_matches(session)[0].started_at + 5, channel="team",
                      text="Thanks! ◇", speaker_raw="Bo", hero="Ana", match_id=first)  # fmt: skip
    await user.open("/")
    user.find(marker="nav-sessions").click()
    user.find(marker=f"session-{session}").click()
    user.find(marker=f"match-{first}").click()
    await user.should_see("+1 callout")
    assert hidden(user, "transcript")
    config.save_show_callouts(True)
    user.find(marker="back-to-matches").click()
    user.find(marker=f"match-{first}").click()
    await user.should_see("Match 1")
    assert not hidden(user, "transcript")

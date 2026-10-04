"""A line's channel, fixed by hand from its popup (#283): stored with what OCR said, never
overwritten by a later reading, Saved + Undo, and kept as a debug sample."""

import json
import time

import pytest
from nicegui.testing import User, user_simulation

from tests.test_sessions import evening
from yaptracker import config, runtime
from yaptracker.debug import DebugSamples
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


def test_the_first_change_keeps_what_ocr_said_and_readings_never_undo_it(store):
    match = store.start_match(store.start_session(1.0), 1.0, "heroselect")
    line = store.add_message(ts=2.0, channel="match", text="gg", match_id=match, speaker_raw="x")
    store.set_channel(line, "team")
    store.set_channel(line, "group")
    assert store.channel_by_hand(line) == ("group", "match")  # the OCR original stays
    store.update_message(line, channel="match", text="gg wp", speaker_raw="x")  # a better read
    assert (store.message(line).channel, store.message(line).text) == ("group", "gg wp")
    store.restore_channel(line, "match", None)  # undo back to "never changed by hand"
    store.update_message(line, channel="team", text="gg wp", speaker_raw="x")
    assert store.message(line).channel == "team"  # readings decide again


async def test_live_fixes_a_channel_with_undo_and_a_debug_sample(
    user: User, store, monkeypatch, tmp_path
):
    config.save_setup_state("done")
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive()
    tracker.chat_changed()
    line = store.add_message(ts=time.time(), channel="match", text="push left", speaker_raw="x",
                             match_id=tracker.match_id)  # fmt: skip
    debug = DebugSamples(tmp_path / "debug", lambda: True)
    monkeypatch.setattr(runtime, "matches", tracker)
    monkeypatch.setattr(runtime, "debug", debug)
    await user.open("/")
    await user.should_see("push left")
    user.find(marker="chat-line").click()
    await user.should_see(marker="channel-seg")
    user.find(marker="channel-team").click()
    assert store.message(line).channel == "team"
    await user.should_see("Channel: Team")
    (sample,) = (tmp_path / "debug" / "corrections").glob("*-ch.json")
    record = json.loads(sample.read_text(encoding="utf-8"))
    assert (record["ocr_channel"], record["fixed_channel"]) == ("match", "team")
    (row,) = user.find(marker=f"line-{line}").elements
    assert "yt-line--team" in row.classes  # the line follows at once
    user.find(marker="undo").click()
    assert store.channel_by_hand(line) == ("match", None)


async def test_a_transcript_line_follows_its_fix(user: User, store):
    config.save_setup_state("done")
    session, first, second = evening(store)
    await user.open("/")
    user.find(marker="nav-sessions").click()
    user.find(marker=f"session-{session}").click()
    user.find(marker=f"match-{second}").click()
    await user.should_see("hi again")
    (hi,) = [m for m in store.messages(second) if m.text == "hi again"]
    user.find(marker=f"line-{hi.id}").click()
    user.find(marker="channel-group").click()
    assert store.message(hi.id).channel == "group"
    (row,) = user.find(marker=f"line-{hi.id}").elements
    assert "yt-line--group" in row.classes and "yt-line--match" not in row.classes


async def test_a_profile_line_opens_the_same_popup(user: User, store):
    config.save_setup_state("done")
    session, first, second = evening(store)
    (hi,) = [m for m in store.messages(second) if m.text == "hi again"]
    await user.open("/")
    user.find(marker="nav-yappers").click()
    user.find(marker=f"yapper-{hi.player_id}").click()
    await user.should_see("hi again")
    user.find(marker=f"line-{hi.id}").click()
    user.find(marker="channel-team").click()
    assert store.message(hi.id).channel == "team"

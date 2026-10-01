"""Sessions (#29): evenings -> matches -> transcript, with gaps where nothing was recorded."""

import time

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.store.repo import Store
from yaptracker.ui import shell

EVENING = time.mktime((2026, 10, 1, 20, 5, 0, 0, 0, -1))  # Thursday, 20:05 local time


def at(minutes: float) -> float:
    return EVENING + minutes * 60


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def evening(store):
    """Two matches on Thursday: one complete, one with 6 minutes not recorded."""
    session = store.start_session(at(0))
    friend = store.add_player("NoodleBonk", at(0))
    store.set_verdict(friend, "friend")
    first = store.start_match(session, at(1), "heroselect", "push", "esperanca")
    store.add_message(ts=at(2), channel="match", text="gl hf", speaker_raw="NoodleBonk",
                      match_id=first, player_id=friend)  # fmt: skip
    store.add_message(ts=at(3), channel="team", text="on it", speaker_raw="Marv",
                      match_id=first, role="me")  # fmt: skip
    store.add_message(ts=at(12), channel="team", text="group up", speaker_raw="Void",
                      match_id=first, role="crew")  # fmt: skip
    store.end_match(first, at(14), "victory")
    second = store.start_match(session, at(16), "endscreen")
    store.add_message(ts=at(17), channel="match", text="hi again", match_id=second,
                      speaker_raw="NoodleBonk", player_id=friend)  # fmt: skip
    gap = store.open_gap(at(20), "no_frames")
    store.close_gap(gap, at(26))
    store.add_message(ts=at(27), channel="match", text="gg", speaker_raw="zappy",
                      match_id=second)  # fmt: skip
    store.end_match(second, at(28), "defeat")
    store.end_session(session, at(30))
    return session, first, second


def test_sessions_newest_first_with_matches_and_yaps(store):
    evening(store)
    later = store.start_session(at(24 * 60))
    store.start_match(later, at(24 * 60 + 1), "gap")  # still running, nobody typed yet
    store.start_session(at(48 * 60))  # YapTracker ran, no match: not worth a row
    rows = store.sessions()
    assert [(r.matches, r.yaps) for r in rows] == [(1, 0), (2, 5)]
    assert rows[0].ended_at == at(24 * 60 + 1)  # never ended: its last sign of life
    assert (rows[1].started_at, rows[1].ended_at) == (at(0), at(30))


def test_session_matches_in_play_order(store):
    session, first, second = evening(store)
    rows = store.session_matches(session)
    assert [(m.id, m.outcome, m.map, m.yaps, m.last_yap) for m in rows] == [
        (first, "victory", "esperanca", 3, at(12)),
        (second, "defeat", None, 2, at(27)),
    ]


def test_gaps_that_overlap_count_touching_ones_dont(store):
    evening(store)
    assert store.gaps_between(at(16), at(28)) == [(at(20), at(26), "no_frames")]
    assert store.gaps_between(at(1), at(14)) == []
    assert store.gaps_between(at(26), at(30)) == []  # ended right as this began
    store.open_gap(at(40), "crash")  # still open: overlaps everything after it
    assert store.gaps_between(at(50), at(60)) == [(at(40), None, "crash")]


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_no_sessions_yet(user: User, store, monkeypatch):
    config.save_setup_state("done")
    monkeypatch.setattr(runtime, "store", store)
    await user.open("/")
    user.find(marker="nav-sessions").click()
    await user.should_see("No sessions yet")


async def test_session_to_match_to_transcript(user: User, store, monkeypatch):
    config.save_setup_state("done")
    session, first, second = evening(store)
    monkeypatch.setattr(runtime, "store", store)
    await user.open("/")
    user.find(marker="nav-sessions").click()
    await user.should_see("Thursday, Oct 1")
    await user.should_see("20:05\u201320:35 \u00b7 30 min \u00b7 2 matches \u00b7 5 yaps")
    user.find(marker=f"session-{session}").click()
    await user.should_see("Match 1 on Esperanca")
    await user.should_see("Push \u00b7 20:06 \u00b7 13 min \u00b7 3 yaps")
    await user.should_see("Match 2")
    user.find(marker=f"match-{second}").click()
    await user.should_see("Match 2")
    await user.should_see("Not recorded 20:25\u201320:31 (no picture from Overwatch)")
    body = user.find(marker="transcript").elements.pop()
    order = [row.default_slot.children[-1].content if "chat-line" in row._markers else row.text
             for row in body.default_slot.children]  # fmt: skip
    assert order == ["hi again", "Not recorded 20:25\u201320:31 (no picture from Overwatch)", "gg"]
    user.find(marker="back-to-matches").click()
    user.find(marker=f"match-{first}").click()
    await user.should_see("you:")  # own line
    await user.should_see("crew")
    known = [row for row in user.find(marker="chat-line").elements
             if "yt-known--friend" in row.classes]  # fmt: skip
    assert len(known) == 1  # NoodleBonk, in their verdict colour
    user.find(marker="back-to-matches").click()
    user.find(marker="back-to-sessions").click()
    await user.should_see("Thursday, Oct 1")


async def test_the_incomplete_badge(user: User, store, monkeypatch):
    config.save_setup_state("done")
    session, _, second = evening(store)
    monkeypatch.setattr(runtime, "store", store)
    await user.open("/")
    user.find(marker="nav-sessions").click()
    user.find(marker=f"session-{session}").click()
    await user.should_see(marker="incomplete")
    (badge,) = user.find(marker="incomplete").elements  # match 1 was complete
    assert f"match-{second}" in badge.parent_slot.parent._markers

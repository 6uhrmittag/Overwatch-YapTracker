"""Chat read after the match says so (#501): what waits per match, the time left, and the
badges, the transcript banner and Live's line, until it's read through."""

import asyncio
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.later import Backlog, LaterFrames
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.reader import ChatReader
from yaptracker.store.repo import Store
from yaptracker.ui import backlog, shell

T0 = 1_000_000.0
EVENING = time.mktime((2026, 10, 1, 20, 5, 0, 0, 0, -1))  # Thursday, 20:05 local time


def frame():
    return np.zeros((40, 400, 3), np.uint8)


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def test_what_waits_per_match_in_reading_order():
    later = LaterFrames(lambda: 0.0, None)
    for n in range(3):
        later.add(T0 + n, frame(), 1, "after")
    for n in range(2):
        later.add(T0 + 10 + n, frame(), 2, "after")
    assert later.waiting() == ({1: (3, 0), 2: (2, 0)}, 0)
    later.pop()
    assert later.waiting()[0] == {1: (3, 0), 2: (2, 0)}  # being read: its lines aren't in yet
    later.finish()
    assert later.waiting()[0] == {1: (2, 1), 2: (2, 0)}
    later.pop()
    later.pop()  # the one before is read by now
    assert later.waiting()[0] == {1: (1, 2), 2: (2, 0)}
    later.finish()
    assert later.waiting()[0] == {2: (2, 0)}  # read through: no badge left
    later.add(T0 + 20, frame(), 2, "light")  # a live frame of match 2 queues behind
    later.pop()
    later.finish()
    assert later.waiting()[0] == {2: (2, 1)}  # its count goes on, never back to 0 of 1
    while later.pop() is not None:
        later.finish()
    assert later.waiting() == ({}, 0)


def test_pictures_from_the_last_run_wait_in_their_matches(tmp_path):
    unread = tmp_path / "unread"
    later = LaterFrames(lambda: 0.0, None, unread=unread)
    for n, match in enumerate([4, 4, 5]):
        later.add(T0 + n, frame(), match, "after")
    assert later.close() is None
    again = LaterFrames(lambda: 0.0, None, unread=unread)
    assert again.restore(now=T0 + 3600) is None
    assert again.waiting() == ({4: (2, 0), 5: (1, 0)}, 3) and again.restored() == 3  # (#474)


def test_which_match_reads_now_and_how_long_it_takes():
    waiting = Backlog({1: (3, 2), 2: (4, 0)}, 0.5, False, 2)
    assert (waiting.state(1), waiting.state(2), waiting.state(3)) == ("reading", "waiting", None)
    assert (waiting.seconds_left(1), waiting.seconds_left(), waiting.left) == (1.5, 3.5, 7)
    running = Backlog({1: (3, 0), 2: (4, 0)}, 1.0, True, 2)  # match 2 runs, read afterwards
    assert (running.state(1), running.state(2), running.earlier()) == ("waiting", "after", [1])
    between = Backlog({None: (2, 0), 7: (5, 0)}, 1.0, False, 7)  # kept outside a match first
    assert between.state(7) == "waiting"
    assert backlog.banner(between, 7)[0].startswith(
        "This match's chat waits to be read: 5 pictures (under a minute)."
    )
    assert backlog.day_badge(running, (1, 2)) == "Waiting to be read"
    assert backlog.day_badge(Backlog({1: (3, 0)}, 1.0, False, 2), (1, 2)) == "Still reading"
    assert backlog.day_badge(running, (5,)) is None


def test_the_words():
    waiting = Backlog({1: (3, 2), 2: (140, 0)}, 1.0, False, 2)
    assert backlog.badge(waiting, 1) == "Still reading \u00b7 3 pictures left"
    assert backlog.badge(waiting, 2) == "Waiting to be read"
    assert backlog.badge(None, 1) is None
    assert backlog.banner(waiting, 1) == (
        "Still reading this match's chat: 2 of 5 pictures done (under a minute). "
        "New lines will keep appearing.",
        0.4,
    )
    assert backlog.banner(waiting, 2)[0] == (
        "This match's chat waits to be read: 140 pictures, after 1 earlier match (~2 min). "
        "New lines will keep appearing."
    )
    assert backlog.live(waiting) == "Reading the chat of 2 earlier matches: 143 pictures " \
        "left (~2 min)."  # fmt: skip
    assert backlog.live(Backlog({2: (37, 0)}, 1.0, False, 2)) == (
        "Reading the chat of the last match: 37 pictures left (under a minute)."
    )
    running = Backlog({1: (3, 0), 2: (4, 0), 3: (9, 0)}, 1.0, True, 3)
    assert backlog.during("Competitive", running) == (
        "Competitive: read once it's over. 2 earlier matches still waiting to be read."
    )
    assert backlog.banner(running, 3)[0] == (
        "This match is read once it's over: 9 chat pictures kept so far. Your FPS stays untouched."
    )
    assert (backlog.eta(59), backlog.eta(75), backlog.eta(240)) == (
        "under a minute",
        "~1 min",
        "~4 min",
    )


def test_back_to_back_matches_then_reading_them_with_a_time_left_that_holds(store):
    """Replay: two ranked matches read afterwards, then read at a known pace (50 ms each)."""
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    deferring = threading.Event()
    deferring.set()

    def read(image, mode=None):
        time.sleep(0.05)
        return []

    reader = ChatReader(read, store, tracker, min_gap_s=0.0, read_kept=read,
                        deferring=deferring.is_set)  # fmt: skip
    tracker.new_match(T0, source="heroselect", mode="COMPETITIVE", map_name="Busan")
    first = tracker.match_id
    for _ in range(10):
        reader.offer(frame(), "after")
    tracker.new_match(T0 + 600, source="heroselect", mode="COMPETITIVE")
    second = tracker.match_id
    for _ in range(10):
        reader.offer(frame(), "after")
    waiting = reader.backlog()
    assert waiting.matches == {first: (10, 0), second: (10, 0)}
    assert (waiting.state(first), waiting.state(second)) == ("waiting", "after")
    reader.start()
    try:
        deferring.clear()  # the second match is over: both are read now
        end = time.monotonic() + 10
        while reader.backlog().left > 15:
            assert time.monotonic() < end
            time.sleep(0.01)
        midway = reader.backlog()
        assert midway.state(first) == "reading" and midway.state(second) == "waiting"
        while reader.backlog().left:
            assert time.monotonic() < end
            time.sleep(0.01)
    finally:
        reader.stop()
    assert 0.025 <= reader.per_picture_s <= 0.075  # 50 ms a picture, give or take 50 %


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_days_the_day_and_the_transcript_say_it_until_read_through(
    user: User, store, monkeypatch
):
    config.save_setup_state("done")
    session = store.start_session(EVENING)
    read = store.start_match(session, EVENING + 60, "heroselect", "competitive", "busan")
    store.add_message(ts=EVENING + 120, channel="match", text="gl hf", match_id=read)
    store.end_match(read, EVENING + 900, "victory")
    unread = store.start_match(session, EVENING + 1000, "heroselect", "competitive")
    waiting = {"now": Backlog({read: (37, 63), unread: (140, 0)}, 1.0, False, unread)}
    monkeypatch.setattr(runtime, "store", store)
    reader = SimpleNamespace(backlog=lambda: waiting["now"], tidy_frames=(), tidied=None,
                             wants_reread=lambda: False)  # fmt: skip
    monkeypatch.setattr(runtime, "reader", reader)
    monkeypatch.setattr(backlog, "FOLLOW_S", 0.1)
    await user.open("/")
    user.find(marker="nav-sessions").click()
    await user.should_see("Still reading")
    user.find(marker="day").click()
    await user.should_see("Match 2")  # no yap and no result yet, but its chat is coming
    await user.should_see("Still reading \u00b7 37 pictures left")
    await user.should_see("Waiting to be read")
    user.find(marker=f"match-{read}").click()
    await user.should_see("Still reading this match's chat: 63 of 100 pictures done")
    store.add_message(ts=EVENING + 300, channel="match", text="nice shot", match_id=read)
    waiting["now"] = Backlog({}, 1.0, False, unread)  # read through
    (banner,) = user.find(marker="reading-banner").elements
    for _ in range(30):
        if "yt-hidden" in banner.classes:
            break
        await asyncio.sleep(0.1)
    assert "yt-hidden" in banner.classes
    await user.should_see("nice shot")  # the transcript refreshed itself

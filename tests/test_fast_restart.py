"""#506: a lost capture session comes back within a second or two, not 15-45 s.

Fakes stand in for Windows Graphics Capture: pictures arrive on Windows' side (`last_frame_at`),
the frame loop may be slow, and only the watchdog decides that pictures stopped.
"""

import logging
import threading
import time

import numpy as np
import pytest

from yaptracker.capture.black import SCREEN_SAY, STALLED_SAY, BlackPicture, ScreenFallback
from yaptracker.capture.health import BANNER_AFTER_S, RECONNECT_S, CaptureHealth
from yaptracker.capture.source import Frame
from yaptracker.capture.watcher import FAST_TRIES, CaptureWatcher
from yaptracker.store.repo import Store


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


class FakeWgc:
    """Like WgcFrameSource: plays `pictures`, then Windows either ends the session ("ended") or
    just stops sending ("quiet": frames() waits until it's closed, like its 30 s backstop)."""

    def __init__(self, pictures: int, then: str = "quiet") -> None:
        self.pictures, self.then = pictures, then
        self.last_frame_at = time.monotonic()
        self.closed = threading.Event()
        self.closed_at: float | None = None
        self.first_at: float | None = None

    def frames(self):
        for i in range(self.pictures):
            if self.closed.is_set():
                return
            self.last_frame_at = time.monotonic()
            self.first_at = self.first_at or self.last_frame_at
            yield Frame(i * 0.05, np.zeros((4, 4, 3), np.uint8))
            time.sleep(0.05)
        if self.then == "quiet":
            self.closed.wait(30)

    def close(self) -> None:
        if not self.closed.is_set():
            self.closed_at = time.monotonic()
        self.closed.set()


def wait_for(condition, timeout=5.0):
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def gaps(store):
    return store._read("SELECT reason, ended_at - started_at FROM capture_gaps ORDER BY id")


def opener(sources: list):
    opened = []

    def open_source(hwnd):
        opened.append(sources[len(opened)] if len(opened) < len(sources) else FakeWgc(0))
        return opened[-1]

    return opened, open_source


@pytest.mark.parametrize("then", ["ended", "quiet"])
def test_a_lost_session_is_back_within_two_seconds_and_a_short_gap(store, then):
    health = CaptureHealth(store)
    opened, open_source = opener([FakeWgc(3, then), FakeWgc(1000)])
    watcher = CaptureWatcher(lambda: 42, open_source, health=health,
                             stall_s=lambda: 0.5)  # fmt: skip
    watcher.start()
    try:
        wait_for(lambda: len(opened) == 2 and opened[1].first_at and health.gap is None)
    finally:
        watcher.stop()
    lost_at = opened[0].last_frame_at
    assert opened[1].first_at - lost_at <= 2.0  # Windows ended it, or 0.5 s without a picture
    ((reason, length),) = gaps(store)
    assert reason == ("window_lost" if then == "ended" else "no_frames") and length <= 3.0


def test_a_slow_frame_handler_does_not_delay_noticing_the_stall():
    """A Live render holding the database for seconds (`ui: live took 7-24 s`) slowed the frame
    loop; the watchdog runs on its own thread."""
    release = threading.Event()
    opened, open_source = opener([FakeWgc(2), FakeWgc(1000)])

    def slow_handler(frame):
        release.wait(10)  # the frame loop is stuck here, like a store write behind the UI

    watcher = CaptureWatcher(lambda: 42, open_source, slow_handler, stall_s=lambda: 0.3)
    watcher.start()
    try:
        wait_for(lambda: opened[0].closed_at is not None, timeout=2.0)
        assert opened[0].closed_at - opened[0].last_frame_at < 1.5  # 0.3 s + a tick or two
    finally:
        release.set()
        watcher.stop()


def failing_restarts(in_front: bool, store) -> list[int]:
    switched = []
    sources = [FakeWgc(2, "ended")] + [FakeWgc(0, "ended") for _ in range(FAST_TRIES + 2)]
    opened, open_source = opener(sources)
    watcher = CaptureWatcher(lambda: 42, open_source, health=CaptureHealth(store), retry_s=0.01,
                             in_front=lambda w: in_front, on_failing=switched.append,
                             poll_s=10)  # fmt: skip
    watcher.start()
    try:
        wait_for(lambda: len(opened) >= FAST_TRIES + 2)
    finally:
        watcher.stop()
    return switched


def test_five_failed_restarts_with_overwatch_in_front_read_the_screen(store):
    assert failing_restarts(True, store) == [42]


def test_failed_restarts_while_alt_tabbed_dont_switch(store):
    assert failing_restarts(False, store) == []  # minimised: no picture is expected


def test_sessions_that_die_after_their_first_picture_count_as_failed_restarts(store):
    """A new WGC session sends one picture at once: that alone doesn't make a restart work."""
    switched = []
    opened, open_source = opener([FakeWgc(1, "ended") for _ in range(FAST_TRIES + 3)])
    watcher = CaptureWatcher(lambda: 42, open_source, health=CaptureHealth(store), retry_s=0.01,
                             in_front=lambda w: True, on_failing=switched.append,
                             poll_s=10)  # fmt: skip
    watcher.start()
    try:
        wait_for(lambda: switched)
    finally:
        watcher.stop()
    assert switched == [42]


def test_failed_restarts_start_over_when_the_game_closes():
    watcher = CaptureWatcher(lambda: None, lambda _: None, poll_s=10)
    watcher._failures, watcher._front_failures = 3, FAST_TRIES - 1
    watcher.start()
    try:
        wait_for(lambda: watcher._front_failures == 0, timeout=2.0)
    finally:
        watcher.stop()
    assert watcher._failures == 0


def test_retries_wait_once_a_second_then_longer():
    watcher = CaptureWatcher(lambda: None, lambda _: None, poll_s=2.0)
    waits = []
    for failures in range(1, FAST_TRIES + 4):
        watcher._failures, watcher._opened_at = failures, -100.0
        waits.append(watcher._retry_wait())
    assert waits == [0.0] + [1.0] * FAST_TRIES + [2.0, 4.0]


def test_a_late_watchdog_tick_is_logged(caplog):
    ticks = iter([0.0, 3.5, 4.0])
    watcher = CaptureWatcher(lambda: None, lambda _: None, poll_s=10,
                             clock=lambda: next(ticks, 4.0))  # fmt: skip
    with caplog.at_level(logging.INFO, logger="yaptracker.capture.watcher"):
        watcher.start()
        wait_for(lambda: "late" in caplog.text, timeout=3.0)
        watcher.stop()
    assert "watchdog tick 3.0 s late" in caplog.text


def test_the_screen_after_failed_restarts_lasts_until_overwatch_closes():
    saved = []
    screen = ScreenFallback(BlackPicture(lambda: True), False, saved.append)
    assert screen.say == SCREEN_SAY
    screen.stalled()
    assert screen.screen and screen.say == STALLED_SAY and saved == []  # not remembered per PC
    screen.game_closed()
    assert not screen.screen and screen.why is None


def test_a_short_gap_says_reconnecting_and_only_a_long_one_raises_the_banner(store):
    """Every gap is recorded; Live's orange banner waits BANNER_AFTER_S (#506)."""
    now = [1000.0]
    health = CaptureHealth(store, clock=lambda: now[0])
    assert health.state() is None
    health.frame()
    health.lost("no_frames")
    now[0] += BANNER_AFTER_S - 1
    assert health.state() == "reconnecting"
    now[0] += 1
    assert health.state() == "lost"
    health.frame()
    assert health.state() is None and len(gaps(store)) == 1  # the short gap is still a record
    health.paused(True)
    now[0] += 60
    assert health.state() is None  # paused has its own words


def test_a_lost_stretch_is_diagnosed_once_and_its_end_noted(store):
    ended, back = [], []
    sources = [FakeWgc(2, "ended"), FakeWgc(0, "ended"), FakeWgc(0, "ended"), FakeWgc(1000)]
    opened, open_source = opener(sources)
    watcher = CaptureWatcher(lambda: 42, open_source, health=CaptureHealth(store), retry_s=0.01,
                             on_ended=lambda w, why: ended.append((w, why)),
                             on_back=lambda: back.append(1))  # fmt: skip
    watcher.start()
    try:
        wait_for(lambda: back)
    finally:
        watcher.stop()
    assert ended == [(42, "Windows ended the capture session")] and back == [1]


def test_overwatch_losing_and_regaining_focus_is_logged(caplog):
    front = [True]
    opened, open_source = opener([FakeWgc(1000)])
    watcher = CaptureWatcher(lambda: 42, open_source, in_front=lambda w: front[0])
    with caplog.at_level(logging.INFO, logger="yaptracker.capture.watcher"):
        watcher.start()
        try:
            wait_for(lambda: watcher._in_focus is True)
            front[0] = False
            wait_for(lambda: "lost focus" in caplog.text)
            front[0] = True
            wait_for(lambda: "in front again" in caplog.text)
        finally:
            watcher.stop()
    assert watcher.focus_note().startswith("focus: lost ") and ", back " in watcher.focus_note()


def test_a_session_that_dies_after_each_picture_is_diagnosed_once(store):
    """Each one-picture session resets the failure count: still one stretch, one sample (#506)."""
    ended, back = [], []
    sources = [FakeWgc(1, "ended") for _ in range(3)] + [FakeWgc(1000)]
    opened, open_source = opener(sources)
    watcher = CaptureWatcher(lambda: 42, open_source, health=CaptureHealth(store), retry_s=0.01,
                             on_ended=lambda w, why: ended.append(why),
                             on_back=lambda: back.append(1))  # fmt: skip
    watcher.start()
    try:
        wait_for(lambda: len(opened) == 4 and opened[3].first_at is not None)
    finally:
        watcher.stop()
    assert ended == ["Windows ended the capture session"] and back == [1]


def test_a_late_noticed_loss_still_gets_a_few_seconds_of_reconnecting(store):
    """A stall is noticed 10 s after the last picture: still "reconnecting" at first (#506)."""
    now = [1000.0]
    health = CaptureHealth(store, clock=lambda: now[0])
    health.frame()
    now[0] += 10  # the watchdog's 10 s between matches
    health.lost("no_frames")
    assert health.state() == "reconnecting" and health.gap.since == 1000.0
    now[0] += RECONNECT_S
    assert health.state() == "lost"


def test_a_new_launch_doesnt_start_its_gap_at_the_last_evenings_picture(store):
    now = [1000.0]
    health = CaptureHealth(store, clock=lambda: now[0])
    health.frame()
    health.game_closed()
    now[0] += 3600
    health.lost("crash")  # the next launch's first session died before a picture
    assert health.gap.since == now[0] and health.state() == "reconnecting"

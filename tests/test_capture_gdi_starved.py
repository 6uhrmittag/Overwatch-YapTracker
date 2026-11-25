"""The GDI capture (Windows 10, the screen fallback) under a starved app (#605): the watcher's
watchdog decides with the rule of #601, not a wall-clock timeout of the source's own. The screen
grab is faked: this runs everywhere."""

import threading
import time

import numpy as np
import pytest

from yaptracker.capture import gdi
from yaptracker.capture.source import CaptureStalled, Region
from yaptracker.capture.watcher import TICK_S, CaptureWatcher


class Grabber:
    def grab(self, x, y, width, height):
        return np.zeros((max(1, height), max(1, width), 3), np.uint8)

    def close(self) -> None:
        pass


@pytest.fixture
def window(monkeypatch):
    """A fake window: `shown` set = it gives pictures, cleared = minimised."""
    shown = threading.Event()
    shown.set()
    monkeypatch.setattr(gdi, "ScreenGrabber", Grabber)
    monkeypatch.setattr(gdi, "client_area", lambda hwnd: (0, 0, 64, 48) if shown.is_set() else None)
    return shown


def source(**kwargs) -> gdi.GdiFrameSource:
    return gdi.GdiFrameSource(1, lambda w, h: Region(0, 0, w, h), fps=20,
                              covering=lambda hwnd, region: None, **kwargs)  # fmt: skip


def test_it_says_when_it_last_grabbed_the_screen_and_keeps_its_ten_seconds(window):
    capture = source()
    try:
        frames = capture.frames()
        next(frames)
        first = capture.last_frame_at
        next(frames)
        next(frames)
        assert capture.last_frame_at > first
        assert capture.min_stall_s == 10.0
    finally:
        capture.close()


class Stamped:
    """What the watchdog sees of a GDI source: its picture time and its floor."""

    def __init__(self, last_frame_at: float) -> None:
        self.last_frame_at, self.min_stall_s, self.closed = last_frame_at, gdi.MIN_STALL_S, False

    def close(self) -> None:
        self.closed = True


class Health:
    def __init__(self) -> None:
        self.calls = []

    def lost(self, reason: str) -> None:
        self.calls.append(reason)


def watched(now: list[float]) -> tuple[CaptureWatcher, Stamped]:
    watcher = CaptureWatcher(lambda: 1, lambda _: None, clock=lambda: now[0],
                             stall_s=lambda: 3.0, health=Health())  # fmt: skip
    watcher._source = capture = Stamped(now[0])
    watcher._opened_at, watcher._due = now[0], now[0] + TICK_S
    return watcher, capture


def ticks(watcher, now, seconds: float) -> None:
    for _ in range(round(seconds / TICK_S)):
        now[0] += TICK_S
        watcher._tick(now[0])


def test_in_a_match_a_gdi_capture_still_gets_ten_seconds_not_three():
    """Review: its picture time is stamped by our own thread, a slow pass isn't a stall."""
    now = [1000.0]
    watcher, capture = watched(now)
    ticks(watcher, now, 10.0)
    assert not capture.closed
    ticks(watcher, now, 0.5)
    assert capture.closed and watcher._stalled[1] == "no picture from the window for 10 s"


def test_a_starved_gdi_capture_is_not_restarted_and_a_stalled_one_is():
    now = [1000.0]
    watcher, capture = watched(now)
    now[0] += 12.0  # the app didn't run for 12 s: over the old 10 s timeout, no restart
    watcher._tick(now[0])
    assert not capture.closed
    ticks(watcher, now, 9.5)  # on time again and still no picture: 10 s of running time in all
    assert not capture.closed
    ticks(watcher, now, 0.5)
    assert capture.closed


def test_closing_ends_the_frame_loop_also_when_the_capture_thread_is_stuck(window, monkeypatch):
    """Review: only the capture thread ended the loop; stuck, the restart waited 30 s."""
    stuck = threading.Event()
    monkeypatch.setattr(Grabber, "grab", lambda self, *area: stuck.wait(20) or np.zeros((1, 1, 3)))
    capture = source()
    got = []
    reader = threading.Thread(target=lambda: got.extend(capture.frames()))
    reader.start()
    time.sleep(0.2)
    capture._thread.join = lambda timeout=None: None  # don't wait for the stuck thread here
    capture.close()
    reader.join(3.0)
    alive = reader.is_alive()
    stuck.set()
    assert not alive and got == []


def test_its_own_backstop_counts_a_wait_that_took_longer_as_the_wait_asked_for(window):
    window.clear()
    capture = source(stall_s=1.0)
    try:
        started = time.monotonic()
        with pytest.raises(CaptureStalled, match="for 1 s"):
            next(capture.frames())
        assert 0.9 <= time.monotonic() - started < 5.0  # two waits of 0.5 s
    finally:
        capture.close()


def test_in_a_match_a_long_wait_without_a_picture_is_a_gap_for_gdi_too():
    """#618: its limit stays 10 s, so "in a match" was never seen: no restart and no gap."""
    now = [1000.0]
    watcher, capture = watched(now)
    ticks(watcher, now, 6.0)
    assert watcher._health.calls == []
    ticks(watcher, now, 0.5)  # more than 6 s: a line can hide in it
    assert watcher._health.calls[:1] == ["no_frames"] and not capture.closed


def test_a_starved_stretch_is_a_gap_for_gdi_too():
    now = [1000.0]
    watcher, capture = watched(now)
    now[0] += 12.0
    watcher._tick(now[0])
    assert watcher._health.calls == ["no_frames"] and not capture.closed

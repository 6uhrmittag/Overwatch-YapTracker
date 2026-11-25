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


def test_it_says_when_it_last_grabbed_the_screen(window):
    capture = source()
    try:
        frames = capture.frames()
        next(frames)
        first = capture.last_frame_at
        next(frames)
        next(frames)
        assert capture.last_frame_at > first
        window.clear()  # minimised: no pictures, and the time stands still
        time.sleep(0.2)
        stood = capture.last_frame_at
        time.sleep(0.2)
        assert capture.last_frame_at == stood
    finally:
        capture.close()


def watched(capture, now: list[float]) -> CaptureWatcher:
    watcher = CaptureWatcher(lambda: 1, lambda _: None, clock=lambda: now[0], stall_s=lambda: 3.0)
    watcher._source = capture
    watcher._opened_at, watcher._due = now[0], now[0] + TICK_S
    return watcher


def test_a_starved_gdi_capture_is_not_restarted_and_a_stalled_one_is(window):
    """The watchdog's clock is driven by hand; the source's picture time is set to match."""
    capture = source()
    try:
        next(capture.frames())
        window.clear()  # from here on its picture time only moves when the test moves it
        time.sleep(0.2)
        now = [1000.0]
        capture.last_frame_at = now[0]
        watcher = watched(capture, now)
        now[0] += 12.0  # the app didn't run for 12 s: over the old 10 s, no restart
        watcher._tick(now[0])
        assert watcher._stalled is None and not capture._closed.is_set()
        for _ in range(13):  # on time again and still no picture: a real stall, 6 s later
            now[0] += TICK_S
            watcher._tick(now[0])
        assert watcher._stalled is not None and capture._closed.is_set()
    finally:
        capture.close()


def test_its_own_backstop_doesnt_count_the_time_it_was_kept_waiting(window, monkeypatch):
    window.clear()
    capture = source(stall_s=3.0)
    try:
        clock = [0.0]
        real_get = capture._queue.get

        def starved_get(timeout):  # every wait "takes" 20 s: the thread got no core
            clock[0] += 20.0
            return real_get(timeout=0.01)

        monkeypatch.setattr(gdi.time, "monotonic", lambda: clock[0])
        monkeypatch.setattr(capture._queue, "get", starved_get)
        with pytest.raises(CaptureStalled, match="for 3 s"):
            next(capture.frames())
        assert clock[0] == 60.0  # each 20 s wait counted as 1 s: three waits, not the first
    finally:
        monkeypatch.undo()
        capture.close()

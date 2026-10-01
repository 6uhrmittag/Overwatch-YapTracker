"""The watcher on Linux with fakes: no game, game appears, game goes away."""

import threading
import time

import numpy as np

from yaptracker.capture.source import Frame
from yaptracker.capture.watcher import CaptureWatcher


class FakeSource:
    def __init__(self, count: int):
        self.count, self.closed = count, False

    def frames(self):
        for i in range(self.count):
            yield Frame(i * 0.25, np.zeros((4, 4, 3), np.uint8))

    def close(self):
        self.closed = True


def wait_for(condition, timeout=2.0):
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def test_waits_quietly_while_the_game_is_closed():
    watcher = CaptureWatcher(lambda: None, lambda hwnd: FakeSource(0), poll_s=0.01)
    watcher.start()
    time.sleep(0.1)
    watcher.stop()
    assert (watcher.state, watcher.frames, watcher.last_error) == ("waiting", 0, None)


def test_captures_while_the_window_exists_and_goes_back_to_waiting():
    windows = iter([None, 42])
    sources, seen = [], []

    def open_source(hwnd):
        assert hwnd == 42
        sources.append(FakeSource(3))
        return sources[-1]

    watcher = CaptureWatcher(lambda: next(windows, None), open_source, seen.append, poll_s=0.01)
    watcher.start()
    wait_for(lambda: len(seen) == 3 and watcher.state == "waiting")
    watcher.stop()
    assert watcher.frames == 3 and sources[0].closed


def test_a_failing_capture_is_reported_and_retried():
    attempts = threading.Semaphore(0)

    def open_source(hwnd):
        attempts.release()
        raise OSError("capture item could not be created")

    watcher = CaptureWatcher(lambda: 42, open_source, poll_s=0.01)
    watcher.start()
    assert attempts.acquire(timeout=2) and attempts.acquire(timeout=2)
    watcher.stop()
    assert watcher.last_error == "capture item could not be created"


def test_frames_are_dropped_while_paused():
    seen = []
    watcher = CaptureWatcher(lambda: 42, lambda hwnd: FakeSource(3), seen.append, poll_s=10,
                             paused=lambda: True)  # fmt: skip
    watcher.start()
    wait_for(lambda: watcher.frames >= 3)
    watcher.stop()
    assert seen == [] and watcher.last_frame is None


def test_match_signals_keep_running_while_paused():
    class WithSignals(FakeSource):
        def frames(self):
            for i in range(self.count):
                yield Frame(i * 0.25, np.zeros((4, 4, 3), np.uint8), {"heroselect": np.zeros(1)})

    chat, signals = [], []
    watcher = CaptureWatcher(lambda: 42, lambda hwnd: WithSignals(3), chat.append, poll_s=10,
                             paused=lambda: True, on_signals=signals.append)  # fmt: skip
    watcher.start()
    wait_for(lambda: len(signals) >= 3)
    watcher.stop()
    assert chat == [] and len(signals) == 3  # chat dropped, match signals still read (#93)

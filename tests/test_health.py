"""Capture health (#75): supervisor restarts and gap records, with fake frame sources."""

import time

import numpy as np
import pytest

from yaptracker.capture.health import CaptureHealth
from yaptracker.capture.source import CaptureStalled, Frame
from yaptracker.capture.watcher import CaptureWatcher
from yaptracker.store.repo import Store


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def gaps(store):
    return store._read("SELECT reason, ended_at IS NOT NULL FROM capture_gaps ORDER BY id")


class Script:
    """A frame source that plays frames and then ends the way it's told to."""

    def __init__(self, frames, then=None):
        self.count, self.then, self.closed = frames, then, False

    def frames(self):
        for i in range(self.count):
            yield Frame(i * 0.25, np.zeros((4, 4, 3), np.uint8))
        if self.then is not None:
            raise self.then

    def close(self):
        self.closed = True


def run_until(watcher, condition, timeout=3.0):
    watcher.start()
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)
    watcher.stop()


def test_a_crash_is_a_gap_until_pictures_come_back(store):
    health = CaptureHealth(store)
    sources = iter([Script(3, OSError("device lost")), Script(3)])
    windows = iter([1, 1, None])  # capture (crashes), capture again, then the game is closed
    watcher = CaptureWatcher(lambda: next(windows, None), lambda _: next(sources), health=health,
                             poll_s=0.01)  # fmt: skip
    run_until(watcher, lambda: len(gaps(store)) == 1 and health.gap is None)
    assert gaps(store) == [("crash", 1)]


def test_no_pictures_for_a_while_restarts_the_capture_and_records_the_gap(store):
    health = CaptureHealth(store)
    sources = iter([Script(2, CaptureStalled("no picture for 10 s")), Script(2)])
    opened = []

    def open_source(_):
        opened.append(1)
        return next(sources)

    windows = iter([1, 1, None])  # capture (stalls), capture again, then the game is closed
    watcher = CaptureWatcher(lambda: next(windows, None), open_source, health=health, poll_s=0.01)
    run_until(watcher, lambda: len(opened) == 2 and health.gap is None and gaps(store))
    assert gaps(store) == [("no_frames", 1)]


def test_losing_the_window_while_the_game_still_runs_is_a_gap(store):
    health = CaptureHealth(store)
    sources = iter([Script(2), Script(2)])
    windows = iter([1, 1, 1, None])  # capture, window still there after it ended, capture, gone
    watcher = CaptureWatcher(lambda: next(windows, None), lambda _: next(sources), health=health,
                             poll_s=0.01)  # fmt: skip
    run_until(watcher, lambda: gaps(store) and health.gap is None)
    assert gaps(store) == [("window_lost", 1)]


def test_closing_the_game_normally_loses_nothing(store):
    health = CaptureHealth(store)
    windows = iter([1, None])
    watcher = CaptureWatcher(lambda: next(windows, None), lambda _: Script(3), health=health,
                             poll_s=0.01)  # fmt: skip
    run_until(watcher, lambda: watcher.frames == 3 and watcher.state == "waiting")
    assert gaps(store) == []


def test_a_pause_is_recorded_as_a_gap_too(store):
    health = CaptureHealth(store)
    health.frame()
    health.paused(True)
    assert health.gap.reason == "paused"
    health.paused(False)
    assert gaps(store) == [("paused", 1)]


def test_the_first_reason_wins_and_the_gap_starts_at_the_last_picture(store):
    clock = iter([100.0, 130.0, 160.0]).__next__
    health = CaptureHealth(store, clock=clock)
    health.frame()  # last picture at 100
    health.lost("no_frames")
    health.lost("crash")
    assert health.gap.reason == "no_frames" and health.gap.since == 100.0


def spans(store):
    return store._read("SELECT started_at, ended_at, reason FROM capture_gaps ORDER BY id")


def test_overwatch_running_before_yaptracker_is_a_gap_from_the_game_start(store):
    now = 20 * 3600.0 + 1800
    health = CaptureHealth(store, clock=lambda: now)
    health.started_late(game_started_at=20 * 3600.0, last_activity=None)
    assert spans(store) == [(20 * 3600.0, now, "app_not_running")]


def test_a_restart_mid_evening_only_loses_the_time_it_was_gone(store):
    now = 21 * 3600.0
    health = CaptureHealth(store, clock=lambda: now)
    health.started_late(game_started_at=19 * 3600.0, last_activity=20 * 3600.0 + 3000)
    assert spans(store) == [(20 * 3600.0 + 3000, now, "app_not_running")]


def test_a_few_seconds_late_or_an_unknown_start_is_no_gap(store):
    now = 1000.0
    health = CaptureHealth(store, clock=lambda: now)
    health.started_late(game_started_at=now - 10, last_activity=None)
    health.started_late(game_started_at=None, last_activity=None)
    assert spans(store) == []

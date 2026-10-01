"""What the capture delivers (#187): frames/s from Windows, our time per frame, in log and UI."""

import logging

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config
from yaptracker.capture import stats
from yaptracker.capture.stats import CaptureStats
from yaptracker.ui import shell


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_rate_and_cost_logged_once_a_minute(caplog):
    clock = Clock()
    capture = CaptureStats(4.0, clock=clock)
    caplog.set_level(logging.INFO, logger="yaptracker.capture.stats")
    for _ in range(4 * 61):  # Windows delivers 4 frames a second, 2 ms each here
        capture.frame(0.002)
        clock.now += 0.25
    assert capture.per_second() == pytest.approx(4.0)
    (line,) = [r.getMessage() for r in caplog.records]
    assert line == "capture: 4.0 frames/s from Windows (asked for 4), 2.0 ms per frame here"


def test_nothing_lately_is_none():
    clock = Clock()
    capture = CaptureStats(clock=clock)
    capture.frame(0.001)
    assert capture.per_second() is None  # one frame is no rate
    capture.frame(0.001)
    clock.now += 30
    assert capture.per_second() is None  # stopped a while ago


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_settings_shows_the_capture_rate(user: User, monkeypatch):
    config.save_setup_state("done")
    clock = Clock()
    capture = CaptureStats(4.0, clock=clock)
    for _ in range(20):
        capture.frame(0.001)
        clock.now += 1 / 30  # this Windows ignores the asked rate
    monkeypatch.setattr(stats, "CAPTURE", capture)
    monkeypatch.setattr("yaptracker.ui.views.CAPTURE", capture)
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("Capture: 30.0 frames/s from Windows (asked for 4)")

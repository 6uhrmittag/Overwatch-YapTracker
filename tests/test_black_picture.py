"""A black picture from Windows (#217): exclusive Fullscreen is said in words, in Live, in setup
and in calibration, and a black snapshot is never the picture to draw on. Fakes, no game."""

import logging

import numpy as np
import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.capture.black import SAY, BlackPicture, is_black
from yaptracker.capture.watcher import CaptureWatcher
from yaptracker.ui import shell

BLACK = np.zeros((135, 240, 3), np.uint8)
GAME = np.full((135, 240, 3), 60, np.uint8)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_black_only_when_windows_sends_nothing_but_black():
    assert is_black(BLACK) and not is_black(GAME) and not is_black(None)
    dark_scene = BLACK.copy()
    dark_scene[60:70, 100:140] = 40  # a dark map still has something on it
    assert not is_black(dark_scene)


def test_said_after_a_few_seconds_in_front_logged_once(caplog):
    clock, front = Clock(), {"on": True}
    black = BlackPicture(lambda: front["on"], clock)
    with caplog.at_level(logging.WARNING, logger="yaptracker.capture.black"):
        black.update(BLACK)
        assert not black.black  # a fade between screens isn't it
        for _ in range(3):
            clock.now += 5
            black.update(BLACK)
        assert black.black
        black.update(GAME)
        assert not black.black
        front["on"] = False  # alt-tabbed: not a fair test
        for _ in range(3):
            clock.now += 5
            black.update(BLACK)
        assert not black.black
    assert len([r for r in caplog.records if "black picture" in r.getMessage()]) == 1


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


def capturing(monkeypatch, snapshot=None) -> CaptureWatcher:
    watcher = CaptureWatcher(lambda: None, lambda _: None)
    watcher.state = "capturing"
    monkeypatch.setattr(watcher, "snapshot", lambda timeout=2.0: snapshot)
    monkeypatch.setattr(runtime, "watcher", watcher)
    monkeypatch.setattr(runtime, "window_size", (2560, 1440))
    return watcher


def a_black_picture(monkeypatch) -> None:
    black = BlackPicture(lambda: True)
    black.black = True
    monkeypatch.setattr(runtime, "black", black)


async def test_live_says_it(user: User, monkeypatch):
    config.save_setup_state("done")
    a_black_picture(monkeypatch)
    await user.open("/")
    await user.should_see(SAY)


async def test_setup_never_says_perfect_then(user: User, monkeypatch):
    capturing(monkeypatch)
    a_black_picture(monkeypatch)
    await user.open("/")
    await user.should_see("Found Overwatch at 2560×1440.")
    await user.should_see(SAY)
    await user.should_not_see("Borderless windowed, perfect.")


async def test_a_black_snapshot_isnt_the_picture_to_draw_on(user: User, monkeypatch):
    config.save_setup_state("done")
    capturing(monkeypatch, snapshot=np.zeros((1440, 2560, 3), np.uint8))
    await user.open("/")
    user.find(marker="nav-settings").click()
    user.find(marker="calibrate").click()
    await user.should_see(marker="black-snapshot", retries=50)
    await user.should_not_see("615 × 395 px at 55, 510")  # no box drawn on a black picture


async def test_calibration_without_the_game_explains_itself(user: User):
    config.save_setup_state("done")
    await user.open("/")
    user.find(marker="nav-settings").click()
    user.find(marker="calibrate").click()
    await user.should_see("I can't see Overwatch right now")
    await user.should_see("Pick a screenshot file")

"""A black picture from Windows (#217): exclusive Fullscreen is said in words, in Live, in setup
and in calibration, and a black snapshot is never the picture to draw on. Fakes, no game."""

import logging
import time

import numpy as np
import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.capture.black import SAY, BlackPicture, ScreenFallback, is_black
from yaptracker.capture.source import Frame
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


def test_a_black_window_switches_to_the_screen_once_and_is_remembered(caplog):
    clock, saved = Clock(), []
    black = BlackPicture(lambda: True, clock)
    fallback = ScreenFallback(black, remembered=False, remember=saved.append)
    black.update(GAME)
    assert not fallback.check(window_capture=True)
    black.update(BLACK)
    assert not fallback.check(window_capture=True)  # a fade between screens isn't it
    clock.now += 5
    black.update(BLACK)
    with caplog.at_level(logging.WARNING, logger="yaptracker.capture.black"):
        assert fallback.check(window_capture=True) and fallback.screen
    assert saved == [True] and "reading the screen" in caplog.text
    assert not fallback.check(window_capture=False)  # once: the screen is read now


def test_screen_capture_is_never_a_reason_to_switch():
    black = BlackPicture(lambda: True, Clock())
    black.black = True  # GDI on Windows 10 (#248) is the screen already: Fullscreen, then
    assert not ScreenFallback(black, False, lambda on: None).check(window_capture=False)


def test_remembered_switches_at_the_first_black_picture_and_forgets_a_working_window():
    saved = []
    black = BlackPicture(lambda: True, Clock())
    fallback = ScreenFallback(black, remembered=True, remember=saved.append)
    black.update(BLACK)
    assert fallback.check(window_capture=True) and saved == []  # remembered already

    black = BlackPicture(lambda: True, Clock())  # the next start: the window works again
    fallback = ScreenFallback(black, remembered=True, remember=saved.append)
    black.update(GAME)
    assert not fallback.check(window_capture=True) and saved == [False]
    black.update(BLACK)
    assert not fallback.check(window_capture=True)  # back to waiting a few seconds


def test_reopen_closes_the_capture_and_opens_it_again_without_a_gap():
    class Endless:
        def __init__(self):
            self.closed = False

        def frames(self):
            while not self.closed:
                yield Frame(0.0, GAME, {"overview": GAME})
                time.sleep(0.01)

        def close(self):
            self.closed = True

    class Health:
        def __getattr__(self, name):
            return lambda *args: calls.append(name)

    calls, sources, reopened = [], [], []

    def open_source(hwnd):
        sources.append(Endless())
        return sources[-1]

    def on_signals(frame):
        if len(sources) == 1:
            watcher.reopen()
        elif not reopened:
            reopened.extend(calls)  # what health heard until the second capture ran

    watcher = CaptureWatcher(lambda: 42, open_source, health=Health(), on_signals=on_signals,
                             poll_s=10)  # fmt: skip
    watcher.start()
    deadline = time.monotonic() + 2
    while not reopened and time.monotonic() < deadline:
        time.sleep(0.01)
    watcher.stop()
    assert len(sources) == 2 and sources[0].closed and "lost" not in reopened


async def test_live_and_about_say_the_screen_is_read(user: User, monkeypatch):
    capturing(monkeypatch)
    black = BlackPicture(lambda: True)
    fallback = ScreenFallback(black, False, lambda on: None)
    fallback.screen = True
    monkeypatch.setattr(runtime, "black", black)
    monkeypatch.setattr(runtime, "screen", fallback)
    config.save_setup_state("done")
    await user.open("/")
    await user.should_see("Listening for yaps")
    (banner,) = user.find(marker="screen-capture").elements
    (black_banner,) = user.find(marker="black-picture").elements
    assert "yt-hidden" not in banner.classes and "yt-hidden" in black_banner.classes
    user.find(marker="nav-settings").click()
    await user.should_see(marker="capture-screen")

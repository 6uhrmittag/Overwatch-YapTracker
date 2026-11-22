"""#560: Overwatch's window is black while the game starts. That mustn't switch capture to the
screen, and being on the screen isn't for the whole evening: the window is tried again at every
match start and every few minutes between matches. Fake capture, no game."""

import logging
import time

import numpy as np

from yaptracker.capture.black import (
    BLACK_FOR_S,
    PROBE_S,
    RETRY_S,
    STARTUP_S,
    BlackPicture,
    ScreenFallback,  # fmt: skip
)
from yaptracker.capture.source import Frame
from yaptracker.capture.watcher import FAST_TRIES, CaptureWatcher

BLACK = np.zeros((135, 240, 3), np.uint8)
GAME = np.full((135, 240, 3), 60, np.uint8)


class Evening:
    """The capture thread's part of app.py with fakes: an overview every 5 s, from the window
    (`window`: what it shows, None: nothing arrives) or from the screen (always the game)."""

    def __init__(self, window=BLACK, ran_before: float = 0.0) -> None:
        self.now, self.appeared, self.ran_before = 1000.0, 1000.0, ran_before
        self.window, self.in_front, self.match = window, True, False
        self.black = BlackPicture(lambda: self.in_front, lambda: self.now,
                                  lambda: self.now - self.appeared + self.ran_before)  # fmt: skip
        self.screen = ScreenFallback(self.black, lambda: self.now)
        self.opens: list[str] = []
        self.open()

    def open(self) -> None:
        self.screen.opening()
        self.window_capture = not self.screen.screen
        self.opens.append("window" if self.window_capture else "screen")

    def frame(self) -> None:
        picture = self.window if self.window_capture else GAME
        if picture is None:  # no picture: the watchdog restarts the capture
            return self.open()
        self.black.update(picture)
        if self.screen.check(self.window_capture, self.match):
            self.open()

    def run(self, seconds: float, step: float = 5.0) -> None:
        end = self.now + seconds
        while self.now < end:
            self.frame()
            self.now += step


def test_black_frames_while_overwatch_starts_never_switch_to_the_screen():
    evening = Evening(window=BLACK)
    evening.run(STARTUP_S - 5)  # a long, black start
    evening.window = GAME  # the menu
    evening.run(600)
    assert evening.opens == ["window"] and not evening.screen.screen and not evening.black.black


def test_a_window_that_stays_black_after_the_start_still_switches(caplog):
    evening = Evening(window=BLACK)
    with caplog.at_level(logging.WARNING, logger="yaptracker.capture.black"):
        evening.run(STARTUP_S - 5)
        assert evening.opens == ["window"]
        evening.run(10)
    assert evening.opens == ["window", "screen"] and evening.screen.why == "black"
    assert "reading the screen" in caplog.text


def test_a_running_game_gets_no_startup_minute():
    evening = Evening(window=BLACK, ran_before=3600)  # YapTracker started mid-evening
    evening.run(BLACK_FOR_S - 5)
    assert evening.opens == ["window"]  # a fade or a single black frame never switches
    evening.run(10)
    assert evening.opens == ["window", "screen"]


def on_the_screen() -> Evening:
    evening = Evening(window=BLACK, ran_before=3600)
    evening.run(BLACK_FOR_S + 5)
    assert evening.screen.screen
    return evening


def test_a_match_start_tries_the_window_and_goes_back_when_it_works(caplog):
    evening = on_the_screen()
    evening.window, evening.match = GAME, True
    with caplog.at_level(logging.INFO, logger="yaptracker.capture.black"):
        evening.run(10)
    assert evening.opens == ["window", "screen", "window"]
    assert not evening.screen.screen and not evening.screen.probing
    assert "trying the window again (a match started)" in caplog.text
    assert "back to window capture" in caplog.text
    evening.run(600)  # and it stays there
    assert evening.opens[-1] == "window" and len(evening.opens) == 3


def test_a_window_that_is_still_black_is_dropped_at_its_first_picture():
    evening = on_the_screen()
    evening.match = True
    evening.frame()  # the match started: the window opens ...
    assert evening.opens[-1] == "window" and evening.screen.probing
    evening.now += 1
    evening.frame()  # ... shows black: the screen again, no 20 s wait in hero select
    assert evening.opens[-1] == "screen" and evening.screen.screen
    evening.run(1200)  # in the match: no more tries
    assert evening.opens == ["window", "screen", "window", "screen"]
    evening.match = False
    evening.run(RETRY_S - 10)  # the match is over: once right away, then every few minutes
    assert evening.opens.count("window") == 3 and evening.opens[-1] == "screen"


def test_between_matches_the_window_is_tried_every_few_minutes():
    evening = on_the_screen()
    evening.run(RETRY_S - 10)
    assert evening.opens == ["window", "screen"]
    evening.window = GAME
    evening.run(20)
    assert evening.opens == ["window", "screen", "window"] and not evening.screen.screen


def test_a_tried_window_without_a_picture_goes_back_to_the_screen_at_its_restart():
    evening = on_the_screen()
    evening.window, evening.match = None, True
    evening.frame()  # tried ...
    evening.frame()  # ... nothing came, the watchdog restarted it: on the screen
    assert evening.opens == ["window", "screen", "window", "screen"] and evening.screen.screen
    evening.screen.stalled()  # and a late "it keeps ending" doesn't lock it
    assert evening.screen.why == "black"


def test_no_try_while_overwatch_is_not_in_front_but_right_after():
    evening = on_the_screen()
    evening.in_front, evening.match, evening.window = False, True, GAME
    evening.run(30)
    assert evening.opens == ["window", "screen"]  # alt-tabbed at the match start
    evening.in_front = True
    evening.run(10)
    assert evening.opens == ["window", "screen", "window"] and not evening.screen.screen


def test_a_try_nobody_can_judge_ends_after_a_few_seconds():
    evening = on_the_screen()
    evening.match = True
    evening.frame()
    evening.in_front = False  # alt-tabbed right then: black proves nothing
    evening.run(PROBE_S + 5, step=1.0)
    assert evening.opens[-1] == "screen" and evening.screen.screen


def test_dropped_captures_are_never_tried_again_before_overwatch_closes():
    evening = Evening(window=GAME, ran_before=3600)
    evening.screen.stalled()  # (#506)
    evening.open()
    evening.match = True
    evening.run(RETRY_S * 3)
    assert evening.opens == ["window", "screen"]
    evening.screen.game_closed()
    assert not evening.screen.screen


def test_overwatch_closing_starts_with_the_window_again():
    evening = on_the_screen()
    evening.screen.game_closed()
    assert not evening.screen.screen and evening.screen.why is None


class Quiet:
    """A capture that never brings a picture and ends at once."""

    def frames(self):
        return iter(())

    def close(self) -> None:
        pass


def failing_watcher(clock, switched) -> CaptureWatcher:
    return CaptureWatcher(lambda: 42, lambda _: Quiet(), poll_s=0.01, retry_s=0.0, clock=clock,
                          in_front=lambda w: True, on_failing=switched.append)  # fmt: skip


def test_captures_that_fail_while_overwatch_starts_dont_count_as_dropped():
    switched = []
    watcher = failing_watcher(lambda: 500.0, switched)  # the window just appeared, and stays new
    watcher.start()
    time.sleep(0.3)  # more than FAST_TRIES restarts, all in the first minute
    watcher.stop()
    assert switched == [] and watcher.window_age() == 0.0 and FAST_TRIES > 1

    ticks = iter([500.0])  # appeared at 500; every restart after that is past the first minute
    watcher = failing_watcher(lambda: next(ticks, 500.0 + STARTUP_S), switched)
    watcher.start()
    deadline = time.monotonic() + 3
    while not switched and time.monotonic() < deadline:
        time.sleep(0.01)
    watcher.stop()
    assert switched == [42]  # still failing after the start: that's #506


def test_the_window_age_starts_over_when_overwatch_closes():
    now, window = {"t": 500.0}, {"hwnd": 42}

    class Endless(Quiet):
        closed = False

        def frames(self):
            while not self.closed and window["hwnd"]:
                yield Frame(0.0, GAME)
                time.sleep(0.01)

        def close(self) -> None:
            self.closed = True

    watcher = CaptureWatcher(lambda: window["hwnd"], lambda _: Endless(), poll_s=0.01,
                             clock=lambda: now["t"])  # fmt: skip
    assert watcher.window_age() is None
    watcher.start()
    try:
        time.sleep(0.1)
        now["t"] += 90
        assert watcher.window_age() == 90
        window["hwnd"] = None
        time.sleep(0.2)
        assert watcher.window_age() is None
    finally:
        watcher.stop()

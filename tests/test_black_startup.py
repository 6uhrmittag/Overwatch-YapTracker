"""#560: Overwatch's window is black while the game starts. That mustn't switch capture to the
screen, and being on the screen isn't for the whole evening: the window is tried again at every
match start and every few minutes between matches. Fake capture, no game."""

import logging
import time

import numpy as np

from yaptracker.capture.black import (
    AFTER_MATCH_S,
    BLACK_FOR_S,
    KNOWN_BLACK_FOR_S,
    PROBE_S,
    RETRY_S,
    STARTUP_S,
    BlackPicture,
    ScreenFallback,
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
        self.window, self.in_front, self.match = window, True, None
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
    evening.window, evening.match = GAME, 7
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
    evening.match = 7
    evening.frame()  # the match started: the window opens ...
    assert evening.opens[-1] == "window" and evening.screen.probing
    evening.now += 1
    evening.frame()  # ... shows black: the screen again, no 20 s wait in hero select
    assert evening.opens[-1] == "screen" and evening.screen.screen
    evening.run(1200)  # in the match: no more tries
    assert evening.opens == ["window", "screen", "window", "screen"]
    evening.match = None
    evening.run(AFTER_MATCH_S - 10)  # the match is over: not right away, people say "gg"
    assert evening.opens.count("window") == 2
    evening.run(20)  # then, and every few minutes
    assert evening.opens.count("window") == 3 and evening.opens[-1] == "screen"


def test_a_match_that_follows_a_missed_end_screen_is_a_match_start_too():
    evening = on_the_screen()
    evening.match = 7
    evening.run(10)  # tried, still black
    evening.window, evening.match = GAME, 8  # no "between matches" was ever seen
    evening.run(10)
    assert evening.opens[-1] == "window" and not evening.screen.screen


def test_a_pc_remembered_as_black_switches_sooner_but_never_while_starting():
    saved = []
    evening = Evening(window=BLACK)
    evening.screen = ScreenFallback(evening.black, lambda: evening.now, True, saved.append)
    evening.run(STARTUP_S - 5)
    assert evening.opens == ["window"]  # Marv's evenings: remembered, and a black start
    evening.window = GAME
    evening.run(10)
    assert saved == [False] and evening.opens == ["window"]  # the window works: forgotten

    evening = Evening(window=BLACK, ran_before=3600)
    evening.screen = ScreenFallback(evening.black, lambda: evening.now, True, saved.append)
    evening.frame()
    assert evening.opens == ["window"]  # a single black frame never switches
    evening.run(KNOWN_BLACK_FOR_S + 5)
    assert evening.opens == ["window", "screen"]
    evening.window, evening.match = GAME, 7
    evening.run(10)
    assert evening.opens[-1] == "window" and saved == [False, False]


def test_a_black_window_whose_captures_keep_ending_is_still_tried_again():
    evening = Evening(window=BLACK, ran_before=3600)
    evening.frame()  # black, then the restarts fail five times (#506)
    evening.screen.stalled()
    evening.open()
    assert evening.screen.why == "black"
    evening.window, evening.match = GAME, 7
    evening.run(10)
    assert evening.opens[-1] == "window" and not evening.screen.screen


def test_between_matches_the_window_is_tried_every_few_minutes():
    evening = on_the_screen()
    evening.run(RETRY_S - 10)
    assert evening.opens == ["window", "screen"]
    evening.window = GAME
    evening.run(20)
    assert evening.opens == ["window", "screen", "window"] and not evening.screen.screen


def test_a_tried_window_without_a_picture_goes_back_to_the_screen_at_its_restart():
    evening = on_the_screen()
    evening.window, evening.match = None, 7
    evening.frame()  # tried ...
    evening.frame()  # ... nothing came, the watchdog restarted it: on the screen
    assert evening.opens == ["window", "screen", "window", "screen"] and evening.screen.screen
    evening.screen.stalled()  # and a late "it keeps ending" doesn't lock it
    assert evening.screen.why == "black"


def test_no_try_while_overwatch_is_not_in_front_but_right_after():
    evening = on_the_screen()
    evening.in_front, evening.match, evening.window = False, 7, GAME
    evening.run(30)
    assert evening.opens == ["window", "screen"]  # alt-tabbed at the match start
    evening.in_front = True
    evening.run(10)
    assert evening.opens == ["window", "screen", "window"] and not evening.screen.screen


def test_a_try_nobody_can_judge_ends_after_a_few_seconds():
    evening = on_the_screen()
    evening.match = 7
    evening.frame()
    evening.in_front = False  # alt-tabbed right then: black proves nothing
    evening.run(PROBE_S + 5, step=1.0)
    assert evening.opens[-1] == "screen" and evening.screen.screen


def test_dropped_captures_are_never_tried_again_before_overwatch_closes():
    evening = Evening(window=GAME, ran_before=3600)
    evening.screen.stalled()  # (#506)
    evening.open()
    evening.match = 7
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


def failing_watcher(switched, **more) -> CaptureWatcher:
    return CaptureWatcher(lambda: 42, lambda _: Quiet(), poll_s=0.01, retry_s=0.0,
                          clock=lambda: 500.0, in_front=lambda w: True,
                          on_failing=switched.append, **more)  # fmt: skip


def test_captures_that_fail_while_overwatch_starts_dont_count_as_dropped():
    switched = []
    watcher = failing_watcher(switched)  # the window just appeared, and (fake clock) stays new
    watcher.start()
    time.sleep(0.3)  # more than FAST_TRIES restarts, all in the first minute
    watcher.stop()
    assert switched == [] and watcher.window_age() == 0.0 and FAST_TRIES > 1

    # the same, but Overwatch ran before YapTracker saw it: that's #506
    watcher = failing_watcher(switched, ran_before=lambda: STARTUP_S)
    watcher.start()
    deadline = time.monotonic() + 3
    while not switched and time.monotonic() < deadline:
        time.sleep(0.01)
    watcher.stop()
    assert switched[:1] == [42]


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


def test_overwatch_closing_during_a_reopen_is_still_said():
    """A reopen was asked for and the game went right then: its closing isn't swallowed."""
    window, closed = {"hwnd": 42}, []

    class Once(Quiet):
        def frames(self):
            watcher.reopen()
            window["hwnd"] = None
            yield Frame(0.0, GAME, {"overview": GAME})

    watcher = CaptureWatcher(lambda: window["hwnd"], lambda _: Once(), poll_s=0.01,
                             on_closed=lambda: closed.append(1))  # fmt: skip
    watcher.start()
    deadline = time.monotonic() + 3
    while not closed and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.1)
    watcher.stop()
    assert closed == [1]

"""A black picture from Windows (#217): with Overwatch in exclusive Fullscreen, window capture
gets black frames. Said in words (Live, setup), and logged once with what might apply. When the
window stays black, the screen Overwatch is on is read instead (#236), and the window is tried
again at every match start and every few minutes between matches (#560)."""

import logging
import time
from collections.abc import Callable

import numpy as np

log = logging.getLogger(__name__)
BLACK_MAX = 8  # the brightest pixel of a frame Windows filled with black
BLACK_FOR_S = 20.0  # longer than a fade between screens or a loading screen (#560)
# Overwatch's window is black while the game starts and loads: nothing is concluded from black
# pictures, or from captures that bring none, this long after its window appeared (#560).
STARTUP_S = 60.0
# A PC whose window was black before (remembered) switches sooner: there, every black second is
# chat not read. Still never from one frame, and never while the game starts.
KNOWN_BLACK_FOR_S = 5.0
AFTER_MATCH_S = 60.0  # the end screens have chat ("gg"): no try of the window right then
RETRY_S = 300.0  # on the screen, between matches: try the window again this often (#560)
PROBE_S = 6.0  # a tried window gets this long to show a picture; an overview comes every 5 s
SAY = ("Windows sends me a black picture. Overwatch is probably in Fullscreen: Options → "
       "Video → Display Mode → Borderless Windowed.")  # fmt: skip
SCREEN_SAY = ("Reading the chat box from the screen Overwatch is on: its window gave a black "
              "picture. I try the window again at every match start.")  # fmt: skip
STALLED_SAY = ("Reading the chat box from the screen Overwatch is on: Windows kept dropping the "
               "window capture. Back to the window next time Overwatch starts.")  # fmt: skip


def is_black(image: np.ndarray | None) -> bool:
    return image is not None and image.size > 0 and int(image.max()) <= BLACK_MAX


class BlackPicture:
    """Fed the capture's overview frames (every few seconds, also while paused). `window_age`:
    seconds since Overwatch's window appeared, None when unknown."""

    def __init__(self, in_front: Callable[[], bool],
                 clock: Callable[[], float] = time.monotonic,
                 window_age: Callable[[], float | None] = lambda: None) -> None:  # fmt: skip
        self._in_front, self._clock, self._window_age = in_front, clock, window_age
        self._since: float | None = None
        self._logged = False
        self.black = False  # black for BLACK_FOR_S with Overwatch in front, and not starting
        self.fine = False  # the last overview: Overwatch in front, and a real picture
        self.dark = False  # the last overview: Overwatch in front, and black
        self.for_s = BLACK_FOR_S

    def forget(self) -> None:
        """The capture opens anew (window or screen): the last overview says nothing about it."""
        self.fine = self.dark = False

    def update(self, overview: np.ndarray | None) -> None:
        if overview is None:
            return
        black, in_front = is_black(overview), self._in_front()
        self.fine, self.dark = in_front and not black, in_front and black
        if not black or not in_front:  # alt-tabbed: not a fair test
            self._since, self.black, self._logged = None, False, False
            return
        now = self._clock()
        self._since = now if self._since is None else self._since
        age = self._window_age()
        starting = age is not None and age < STARTUP_S  # loading screens are black (#560)
        self.black = now - self._since >= self.for_s and not starting
        if self.black and not self._logged:
            from yaptracker import system_info

            pc = " | ".join(system_info.machine())
            log.warning("capture: Overwatch is in front, but Windows sends a black picture "
                        "(exclusive Fullscreen?); %s", pc)  # fmt: skip
            self._logged = True


class ScreenFallback:
    """Window capture stays black, but the screen may not be (e.g. the game on the other graphics
    card): then read the screen Overwatch is on, cropped to its window (#236). Not for the whole
    evening (#560): at every match start, and every RETRY_S between matches, the window is tried
    again (a "probe"), and kept as soon as it shows a real picture. A probe that shows black, or
    nothing, goes straight back to the screen. All of it runs on the capture thread.
    Remembered per PC: the next black picture there switches after KNOWN_BLACK_FOR_S, and a real
    picture from the window forgets it again."""

    def __init__(self, black: BlackPicture, clock: Callable[[], float] = time.monotonic,
                 remembered: bool = False,
                 remember: Callable[[bool], None] = lambda on: None) -> None:  # fmt: skip
        self.black, self._clock = black, clock
        self.remembered, self._remember = remembered, remember
        black.for_s = KNOWN_BLACK_FOR_S if remembered else BLACK_FOR_S
        self.screen = False  # read the screen instead of the window
        self.why: str | None = None  # "black" | "stalled" (#506): what Settings says
        self.probing = False  # the window is being tried again
        self._probe_opened = False
        self._tried_at = 0.0
        self._match: int | None = None  # the running match at the last check
        self._match_started = False  # on the screen: a try is owed, once Overwatch is in front

    def check(self, window_capture: bool, match: int | None = None) -> bool:
        """After each signals frame: True when the capture should open again, on the other.
        `match`: the running match's id, None between matches."""
        now = self._clock()
        if match != self._match:  # by id: a missed end screen goes from one match to the next
            if match is None:  # it ended: not now, people say "gg"
                self._tried_at = max(self._tried_at, now - RETRY_S + AFTER_MATCH_S)
            elif self.screen and self.why == "black":
                self._match_started = True
            self._match = match
        if self.probing:
            return self._probed(window_capture, now)
        if self.screen:
            if self.why != "black":
                return False
            due = self._match_started or (match is None and now - self._tried_at >= RETRY_S)
            if not due or not self.black.fine:
                return False  # not in front, or the screen is black too: nothing to gain
            log.info("capture: trying the window again (%s)",
                     "a match started" if self._match_started else "between matches")  # fmt: skip
            self.screen, self.probing, self._probe_opened, self._tried_at = False, True, False, now
            self._match_started = False
            self.black.forget()
            return True
        if not window_capture:
            return False
        if self.black.fine and self.remembered:  # the window gives a picture again on this PC
            self._known(False)
        if not self.black.black:
            return False
        self._known(True)
        log.warning("capture: the window stayed black with Overwatch in front: reading the "
                    "screen it's on instead (#236)")  # fmt: skip
        self.screen, self.why, self._tried_at = True, "black", now
        self.black.forget()
        return True

    def _probed(self, window_capture: bool, now: float) -> bool:
        if not window_capture or not self._probe_opened:
            return False  # a last frame of the screen capture
        if self.black.fine:
            log.info("capture: the window gives a picture again: back to window capture (#560)")
            self.probing, self.why = False, None
            self._known(False)
            return False
        if self.black.dark or now - self._tried_at >= PROBE_S:
            self._probe_failed("still black" if self.black.dark else "no picture to judge")
            return True
        return False

    def _known(self, black: bool) -> None:
        if black != self.remembered:
            self.remembered = black
            self.black.for_s = KNOWN_BLACK_FOR_S if black else BLACK_FOR_S
            self._remember(black)

    def _probe_failed(self, why: str) -> None:
        log.info("capture: the window is no good yet (%s): staying on the screen", why)
        self.screen, self.probing, self._tried_at = True, False, self._clock()
        self.black.forget()

    def opening(self) -> None:
        """A capture opens. A second one during a probe: the tried window brought no picture
        and was restarted, so the screen is read again rather than waiting on it."""
        if self.probing and self._probe_opened:
            self._probe_failed("no picture")
        self._probe_opened = self.probing

    def stalled(self) -> None:
        """Window capture keeps ending with Overwatch in front (#506): the screen until Overwatch
        closes. It's the game's hiccup (since its 2026-11-02 patch), so it isn't tried again
        before that: every try would be a gap. Unless the window was black when it ended: then
        it's the black window (a session of it may bring one picture and no more), tried again
        like one."""
        if self.screen:
            return
        log.warning("capture: the window capture keeps ending: reading the screen Overwatch is on "
                    "instead until it closes (#506)")  # fmt: skip
        self.screen, self.probing = True, False
        self.why, self._tried_at = "black" if self.black.dark else "stalled", self._clock()

    def game_closed(self) -> None:
        """The next Overwatch start tries the window again (#506, #560)."""
        self.screen, self.why, self.probing = False, None, False
        self._match, self._match_started = None, False

    @property
    def say(self) -> str:
        return STALLED_SAY if self.why == "stalled" else SCREEN_SAY

"""A black picture from Windows (#217): with Overwatch in exclusive Fullscreen, window capture
gets black frames. Said in words (Live, setup), and logged once with what might apply. When the
window stays black, the screen Overwatch is on is read instead (#236)."""

import logging
import time
from collections.abc import Callable

import numpy as np

log = logging.getLogger(__name__)
BLACK_MAX = 8  # the brightest pixel of a frame Windows filled with black
BLACK_FOR_S = 5.0  # longer than a fade between screens
SAY = ("Windows sends me a black picture. Overwatch is probably in Fullscreen: Options → "
       "Video → Display Mode → Borderless Windowed.")  # fmt: skip
SCREEN_SAY = ("Capturing the screen Overwatch is on: the window gave a black picture. Keep "
              "other windows off the chat box, what's on top of it is what I read.")  # fmt: skip


def is_black(image: np.ndarray | None) -> bool:
    return image is not None and image.size > 0 and int(image.max()) <= BLACK_MAX


class BlackPicture:
    """Fed the capture's overview frames (every few seconds, also while paused)."""

    def __init__(self, in_front: Callable[[], bool],
                 clock: Callable[[], float] = time.monotonic) -> None:  # fmt: skip
        self._in_front, self._clock = in_front, clock
        self._since: float | None = None
        self._logged = False
        self.black = False
        self.fine = False  # the last overview: Overwatch in front, and a real picture
        self.for_s = BLACK_FOR_S

    def update(self, overview: np.ndarray | None) -> None:
        if overview is None:
            return
        black, in_front = is_black(overview), self._in_front()
        self.fine = in_front and not black
        if not black or not in_front:  # alt-tabbed: not a fair test
            self._since, self.black, self._logged = None, False, False
            return
        now = self._clock()
        self._since = now if self._since is None else self._since
        self.black = now - self._since >= self.for_s
        if self.black and not self._logged:
            from yaptracker import system_info

            pc = " | ".join(system_info.machine())
            log.warning("capture: Overwatch is in front, but Windows sends a black picture "
                        "(exclusive Fullscreen?); %s", pc)  # fmt: skip
            self._logged = True


class ScreenFallback:
    """Window capture stays black, but the screen may not be (e.g. the game on the other graphics
    card): then read the screen Overwatch is on, cropped to its window, for the rest of this run
    (#236). Remembered per PC, so the next start switches at the first black picture; window
    capture is still tried first, and a real picture from it forgets the fallback again."""

    def __init__(self, black: BlackPicture, remembered: bool,
                 remember: Callable[[bool], None]) -> None:  # fmt: skip
        self.black, self.remembered, self._remember = black, remembered, remember
        self.screen = False  # read the screen instead of the window
        black.for_s = 0.0 if remembered else BLACK_FOR_S

    def check(self, window_capture: bool) -> bool:
        """After each signals frame: True when the capture should reopen on the screen."""
        if not window_capture or self.screen:
            return False
        if self.black.fine and self.remembered:  # the window gives a picture again on this PC
            self.remembered, self.black.for_s = False, BLACK_FOR_S
            self._remember(False)
        if not self.black.black:
            return False
        log.warning("capture: the window stayed black with Overwatch in front: reading the "
                    "screen it's on instead (#236)")  # fmt: skip
        self.screen = True
        if not self.remembered:
            self.remembered = True
            self._remember(True)
        return True

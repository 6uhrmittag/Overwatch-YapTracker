"""A black picture from Windows (#217): with Overwatch in exclusive Fullscreen, window capture
gets black frames. Said in words (Live, setup), and logged once with what might apply."""

import logging
import time
from collections.abc import Callable

import numpy as np

log = logging.getLogger(__name__)
BLACK_MAX = 8  # the brightest pixel of a frame Windows filled with black
BLACK_FOR_S = 5.0  # longer than a fade between screens
SAY = ("Windows sends me a black picture. Overwatch is probably in Fullscreen: Options → "
       "Video → Display Mode → Borderless Windowed.")  # fmt: skip


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

    def update(self, overview: np.ndarray | None) -> None:
        if overview is None:
            return
        if not is_black(overview) or not self._in_front():  # alt-tabbed: not a fair test
            self._since, self.black, self._logged = None, False, False
            return
        now = self._clock()
        self._since = now if self._since is None else self._since
        self.black = now - self._since >= BLACK_FOR_S
        if self.black and not self._logged:
            from yaptracker import system_info

            pc = " | ".join(system_info.machine())
            log.warning("capture: Overwatch is in front, but Windows sends a black picture "
                        "(exclusive Fullscreen?); %s", pc)  # fmt: skip
            self._logged = True

"""The game's FPS from Overwatch's own performance overlay (#212), so the FPS test of #187
measures itself: once a minute in the log, tagged with what YapTracker was doing then.

The overlay (Options -> Video -> Display performance stats) is a row of dark boxes at the top
right, right-aligned, `FPS: N` in the leftmost. Every 5 s one thin strip of the screen: find the
row by the box colour at the right edge, then a 1-line read of the FPS box only.
In the menus Overwatch draws it lower, below the menu bar, and caps the game at 60 fps: those
minutes say nothing about YapTracker, so that spot isn't read. When the overlay is off, the
colour check fails and nothing is read or logged. Screen reading only.
"""

import logging
import re
import statistics
import time
from collections.abc import Callable

import numpy as np

from yaptracker.capture.source import Region, RelativeRegion

log = logging.getLogger(__name__)

# Measured on real 2560x1440 screenshots (#212): the box row, from 30 % left of the right edge.
ROW = RelativeRegion.from_pixels(Region(1792, 2, 768, 22), 2560, 1440)
BOX_W = 82  # px at 1440p: the FPS box; VRAM and LATENCY boxes are wider
TEXT_IN = 13  # px at 1440p from the box's left edge to the F of "FPS:"
GAP = 8  # px at 1440p: the boxes are 3-4 px apart (often invisible on a dark background)
TOLERANCE = 24  # per colour channel, around the box colour sampled at the right edge
READ_EVERY_S = 5.0
LOG_EVERY_S = 60.0
_FPS = re.compile(r"FPS\D{0,3}(\d{1,3})", re.IGNORECASE)


def overlay_regions(width: int, height: int) -> dict[str, Region]:
    return {"fps": ROW.to_pixels(width, height)}


def fps_box(strip: np.ndarray, height: int) -> np.ndarray | None:
    """The FPS box of the overlay row in this strip, or None if there is no overlay."""
    s, h = height / 1440, strip.shape[0]
    m = max(1, round(3 * s))  # plain box colour above and below the text, 1 px in from the edge
    margins = np.concatenate([strip[1 : 1 + m], strip[h - 1 - m : h - 1]]).astype(np.int16)
    ref = np.median(margins[:, -round(30 * s) : -round(6 * s)].reshape(-1, 3), axis=0)
    if ref.max() > 130 or ref[0] < ref[2] + 8:  # BGR: the boxes are dark navy
        return None
    plain = (np.abs(margins - ref).max(axis=2) < TOLERANCE).mean(axis=0) > 0.8
    columns = np.flatnonzero(plain)
    if len(columns) == 0 or columns[-1] < len(plain) - 12 * s:
        return None  # the row must reach the right edge
    # Walk left from the right edge over the boxes and the small gaps between them.
    breaks = np.flatnonzero(np.diff(columns) > GAP * s + 1)
    start = int(columns[breaks[-1] + 1]) if len(breaks) else int(columns[0])
    # The leftmost text in the row is the F of "FPS:" (the gaps alone can't be trusted: on a dark
    # background they vanish and the row merges with what's left of it).
    text = strip[round(4 * s) : h - round(4 * s), start:].max(axis=2) > ref.max() + 60
    letters = np.flatnonzero(text.any(axis=0))
    if len(letters) == 0:
        return None
    left = max(0, start + int(letters[0]) - round(TEXT_IN * s))
    box = strip[:, left : left + round(BOX_W * s)]
    return box if box.shape[1] >= BOX_W * s * 0.8 else None


def parse_fps(text: str) -> int | None:
    found = _FPS.search(text)
    return int(found.group(1)) if found else None


class FpsMeter:
    """Reads the overlay every few seconds and logs each minute: median, p10, n and the state.

    `state()` says what YapTracker is doing ("running", "paused"); a new state starts
    a new minute, so every log line is one row of the A/B/C test."""

    def __init__(
        self,
        read_line: Callable[[np.ndarray], str],
        state: Callable[[], str],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._read_line, self._state, self._clock = read_line, state, clock
        self._read_at = -READ_EVERY_S
        self._values: list[int] = []
        self._spent = 0.0
        self._since, self._minute_state = 0.0, ""

    def update(self, signals: dict[str, np.ndarray], height: int) -> None:
        """About once a second, with the capture's crops (the strip is under "fps")."""
        now, state, strip = self._clock(), self._state(), signals.get("fps")
        if self._values and (state != self._minute_state or now - self._since >= LOG_EVERY_S):
            self._log()
        if strip is None or now - self._read_at < READ_EVERY_S:
            return
        self._read_at = now
        started = time.process_time()
        box = fps_box(strip, height)
        value = parse_fps(self._read_line(box)) if box is not None else None
        if value is None:
            return
        if not self._values:
            self._since, self._minute_state = now, state
        self._values.append(value)
        self._spent += time.process_time() - started

    def _log(self) -> None:
        values, spent = self._values, self._spent
        self._values, self._spent = [], 0.0
        log.info(
            "game fps (Overwatch overlay): median %.0f, p10 %.0f, n=%d — %s; %.0f ms CPU per read",
            statistics.median(values), np.percentile(values, 10), len(values), self._minute_state,
            1000 * spent / len(values),
        )  # fmt: skip

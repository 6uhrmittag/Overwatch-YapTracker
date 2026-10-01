"""Match signals from the screen (#93): small crops of the Overwatch window, about once a second.

Hero select shows "ASSEMBLE YOUR TEAM" with a countdown in the top-left corner, and right above
it the mode ("UNRANKED"), the side ("ATTACK") and the map name - all in big type. Seeing the
banner starts a match. Screen reading only, like the chat: never game memory.
"""

import time
from collections.abc import Callable

import cv2
import numpy as np
from rapidfuzz import fuzz

from yaptracker.capture.source import Region, RelativeRegion

# Measured on real 2560x1440 hero-select screenshots (#93), kept as fractions of the window.
HEROSELECT = RelativeRegion.from_pixels(Region(60, 330, 780, 60), 2560, 1440)
HEROSELECT_INFO = RelativeRegion.from_pixels(Region(60, 60, 780, 240), 2560, 1440)
# "PREPARE TO ATTACK 0:44" box, top centre: also at round starts, so only a backup (see below).
ROUND_START = RelativeRegion.from_pixels(Region(1080, 30, 400, 75), 2560, 1440)
BANNER_TEXT = "ASSEMBLE YOUR TEAM"
MATCH = 80  # rapidfuzz ratio on the letters only; OCR may lose or swap a letter or two
# Queue names as Overwatch prints them above the map (the side, ATTACK/DEFEND, follows them).
MODES = ("UNRANKED", "COMPETITIVE", "QUICK PLAY", "ARCADE", "CUSTOM GAME", "PRACTICE")
REARM_S = 120  # the banner must be gone this long before a new hero select counts


def signal_regions(width: int, height: int) -> dict[str, Region]:
    return {
        "heroselect": HEROSELECT.to_pixels(width, height),
        "heroselect_info": HEROSELECT_INFO.to_pixels(width, height),
        "round_start": ROUND_START.to_pixels(width, height),
    }


def has_bright_text(image: np.ndarray, min_pixels: int = 150) -> bool:
    """Cheap check before OCR: enough bright, thin strokes on a darker ground?"""
    value = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[:, :, 2]
    bright = (value > 200).astype(np.uint8)
    thin = bright & ~cv2.morphologyEx(bright, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    return int(thin.sum()) >= min_pixels


def _letters(text: str) -> str:
    return "".join(ch for ch in text.upper() if ch.isalpha())


def is_banner(text: str) -> bool:
    """A whole-text match: a single read letter must never count as "ASSEMBLE YOUR TEAM"."""
    return fuzz.ratio(_letters(text), _letters(BANNER_TEXT)) >= MATCH


def is_round_start(text: str) -> bool:
    """'PREPARE TO ATTACK' / 'PREPARE YOUR DEFENSES' (+ countdown), never a lone letter."""
    letters = _letters(text)
    return len(letters) >= 12 and fuzz.ratio(letters[:7], "PREPARE") >= 85


def parse_info(lines: list[str]) -> tuple[str | None, str | None]:
    """(mode, map): the queue name from the top line, the map name from the bottom one.

    OCR reads e.g. ["UINRANKED ATTACK", "ESPERANCA"]: the mode is matched against the known
    queue names; anything unknown is kept as read rather than guessed.
    """
    lines = [line.strip() for line in lines if line.strip()]
    if not lines:
        return None, None
    top = lines[0].upper()
    best = max(MODES, key=lambda mode: fuzz.partial_ratio(mode, top))
    mode = best if fuzz.partial_ratio(best, top) >= MATCH else lines[0]
    return mode, (lines[-1] if len(lines) > 1 else None)


class HeroSelect:
    """Calls on_start(mode, map) once per hero select."""

    def __init__(
        self,
        read_line: Callable[[np.ndarray], str],
        read_lines: Callable[[np.ndarray], list[str]],
        on_start: Callable[[str | None, str | None], None],
        clock: Callable[[], float] = time.monotonic,
        rearm_s: float = REARM_S,
        match_running: Callable[[], bool] = lambda: False,
    ) -> None:
        self._read_line, self._read_lines = read_line, read_lines
        self._match_running = match_running
        self._on_start, self._clock, self._rearm_s = on_start, clock, rearm_s
        self._active = False
        self._last_seen = 0.0

    def update(self, signals: dict[str, np.ndarray]) -> None:
        strip = signals.get("heroselect")
        if strip is None:
            return
        now = self._clock()
        # The strip is one line: cheap pixel check first, then a fast single-line read.
        if has_bright_text(strip) and is_banner(self._read_line(strip)):
            self._last_seen = now
            if not self._active:
                self._active = True
                info = signals.get("heroselect_info")
                self._on_start(*parse_info(self._read_lines(info) if info is not None else []))
            return
        # Backup: hero select was missed (e.g. YapTracker started late), the round start isn't.
        # Only when no match is running - the same box also shows at later round starts.
        box = signals.get("round_start")
        if (
            not self._active
            and box is not None
            and not self._match_running()
            and has_bright_text(box, min_pixels=60)
            and is_round_start(self._read_line(box))
        ):
            self._active, self._last_seen = True, now
            self._on_start(None, None)
        elif self._active and now - self._last_seen >= self._rearm_s:
            self._active = False

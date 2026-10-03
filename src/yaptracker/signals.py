"""Match signals from the screen (#93, #94): small crops of the Overwatch window, once a second.

Hero select shows "ASSEMBLE YOUR TEAM" with a countdown in the top-left corner, and right above
it the mode ("UNRANKED"), the side ("ATTACK") and the map name - all in big type. Seeing the
banner starts a match. The big "VICTORY!" / "DEFEAT" banner in the centre ends it; "PLAY OF THE
GAME", "VICTORY <MAP>" and the summary screen (top left) follow it as fallbacks.
Screen reading only, like the chat: never game memory.
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
ROUND_START_HEIGHT = 75  # px at 1440p, for has_bright_text
# End of a match (#94): the centre banner, and the title strip in the top-left corner.
END_BANNER = RelativeRegion.from_pixels(Region(900, 590, 820, 250), 2560, 1440)
END_TITLE = RelativeRegion.from_pixels(Region(40, 30, 900, 75), 2560, 1440)
END_TITLE_HEIGHT = 75  # px at 1440p, for has_bright_text
OUTCOMES = {"VICTORY": "victory", "DEFEAT": "defeat", "DRAW": "draw"}
BANNER_TEXT = "ASSEMBLE YOUR TEAM"
MATCH = 80  # rapidfuzz ratio on the letters only; OCR may lose or swap a letter or two
# Queue names as Overwatch prints them above the map (the side, ATTACK/DEFEND, follows them).
MODES = ("UNRANKED", "COMPETITIVE", "QUICK PLAY", "ARCADE", "CUSTOM GAME", "PRACTICE")
SIDES = ("ATTACK", "DEFEND")  # follow the queue name on the hero-select screen
REARM_S = 120  # the banner must be gone this long before a new hero select counts


def signal_regions(width: int, height: int) -> dict[str, Region]:
    return {
        "heroselect": HEROSELECT.to_pixels(width, height),
        "heroselect_info": HEROSELECT_INFO.to_pixels(width, height),
        "round_start": ROUND_START.to_pixels(width, height),
        "end_banner": END_BANNER.to_pixels(width, height),
        "end_title": END_TITLE.to_pixels(width, height),
    }


def _odd(n: float) -> int:
    return max(3, int(round(n)) | 1)


def has_bright_text(image: np.ndarray, min_pixels: int = 150, height_1440: int = 60) -> bool:
    """Cheap check before OCR: enough bright, thin strokes?

    Sizes are for the crop at 1440p (`height_1440` high) and grow with it: 4K strokes are 1.5x
    as thick (#170). Two ways to pass: bright strokes on a darker ground, or strokes clearly
    brighter than what's around them. With HDR on, Windows washes the hero-select screen out to
    near-white, and only the second one still sees "ASSEMBLE YOUR TEAM"."""
    scale = image.shape[0] / height_1440
    value = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[:, :, 2]
    bright = (value > 200).astype(np.uint8)
    thick = cv2.morphologyEx(bright, cv2.MORPH_OPEN, np.ones((_odd(9 * scale),) * 2, np.uint8))
    enough = min_pixels * scale**2
    if int((bright & ~thick).sum()) >= enough:
        return True
    contrast = cv2.morphologyEx(value, cv2.MORPH_TOPHAT, np.ones((_odd(10 * scale),) * 2, np.uint8))
    return int((contrast > 40).sum()) >= enough


def has_colour(image: np.ndarray, min_share: float = 0.08) -> bool:
    """Cheap check before reading the end banner: big, saturated letters fill a good part of it.

    The banner's colour follows the friendly/enemy colour settings, so any hue counts.
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    return float(((hsv[:, :, 1] > 120) & (hsv[:, :, 2] > 170)).mean()) >= min_share


def _letters(text: str) -> str:
    return "".join(ch for ch in text.upper() if ch.isalpha())


LOOSE = 60  # with "TEAM" in it: a very bright map washes out the middle letters (#275)


def is_banner(text: str) -> bool:
    """A whole-text match: a single read letter must never count as "ASSEMBLE YOUR TEAM".
    On a very bright map (New Junk City after the map vote, 2026-10-02) the middle letters
    wash out: "ASSTOL NONRTEAME" scores 64.5 and still counts with its "TEAM"; other text at
    that spot scored at most 42 in the debug samples (#275)."""
    letters = _letters(text)
    score = fuzz.ratio(letters, _letters(BANNER_TEXT))
    return score >= MATCH or (score >= LOOSE and "TEAM" in letters)


def is_round_start(text: str) -> bool:
    """'PREPARE TO ATTACK' / 'PREPARE YOUR DEFENSES' (+ countdown), never a lone letter."""
    letters = _letters(text)
    return len(letters) >= 12 and fuzz.ratio(letters[:7], "PREPARE") >= 85


def banner_outcome(text: str) -> str | None:
    """'VICTORY!' -> 'victory'. Whole-text match; four-letter DRAW must be read exactly."""
    letters = _letters(text)
    for word, outcome in OUTCOMES.items():
        if fuzz.ratio(letters, word) >= (100 if word == "DRAW" else MATCH):
            return outcome
    return None


def title_end(text: str) -> tuple[bool, str | None]:
    """(match over?, outcome) from the top-left title strip after a match.

    Real reads (#94): "PLAY OF THE GAME MAUGA", "VICTORY ESPERANCA", "DEFEATECHENWALDEE" and
    "UMMARYREWARS" (the SUMMARY / REWARDS tabs, first letter cut off).
    """
    letters = _letters(text)
    if fuzz.ratio(letters[:13], "PLAYOFTHEGAME") >= 85:
        return True, None
    if fuzz.ratio(letters[:14], "SUMMARYREWARDS") >= MATCH:
        return True, None
    for word, outcome in OUTCOMES.items():  # the map name follows the outcome
        if len(letters) > len(word) + 2 and fuzz.ratio(letters[: len(word)], word) >= 85:
            return True, outcome
    return False, None


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
    mode = best if fuzz.partial_ratio(best, top) >= MATCH else _without_side(lines[0])
    return mode, (lines[-1] if len(lines) > 1 else None)


def _without_side(text: str) -> str | None:
    """An unknown queue name without the side after it: "STADIUM ATTACK" -> "STADIUM". Only
    the side and a stray letter ("O ATTACK", 4K HDR, #170) is no mode at all."""
    words = [
        w for w in text.split() if all(fuzz.ratio(_letters(w), side) < MATCH for side in SIDES)
    ]
    rest = " ".join(words)
    return rest if len(_letters(rest)) >= 3 else None


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
            and has_bright_text(box, min_pixels=60, height_1440=ROUND_START_HEIGHT)
            and is_round_start(self._read_line(box))
        ):
            self._active, self._last_seen = True, now
            self._on_start(None, None)
        elif self._active and now - self._last_seen >= self._rearm_s:
            self._active = False


class EndScreen:
    """Calls on_end(outcome) once per match end, and again if the outcome only shows up later."""

    def __init__(
        self,
        read_line: Callable[[np.ndarray], str],
        on_end: Callable[[str | None], None],
        clock: Callable[[], float] = time.monotonic,
        rearm_s: float = REARM_S,
        title_every_s: float = 3.0,
    ) -> None:
        self._read_line, self._on_end, self._clock = read_line, on_end, clock
        self._rearm_s, self._title_every_s = rearm_s, title_every_s
        self._active = False
        self._outcome: str | None = None
        self._last_seen = 0.0
        self._title_read = float("-inf")

    def update(self, signals: dict[str, np.ndarray]) -> None:
        now = self._clock()
        seen, outcome = False, None
        banner = signals.get("end_banner")
        # The banner is up for ~4 s: read it every second, unless the outcome is known already.
        if banner is not None and self._outcome is None and has_colour(banner):
            outcome = banner_outcome(self._read_line(banner))
            seen = outcome is not None
        # The title screens stay for 10+ s each: every few seconds is plenty.
        title = signals.get("end_title")
        if not seen and title is not None and now - self._title_read >= self._title_every_s:
            self._title_read = now
            if has_bright_text(title, height_1440=END_TITLE_HEIGHT):
                seen, outcome = title_end(self._read_line(title))
        if seen:
            self._last_seen = now
            if not self._active or (outcome and not self._outcome):
                self._active, self._outcome = True, self._outcome or outcome
                self._on_end(outcome)
        elif self._active and now - self._last_seen >= self._rearm_s:
            self._active, self._outcome = False, None

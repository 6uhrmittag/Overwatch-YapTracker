"""Match signals from the screen (#93, #94): small crops of the Overwatch window, once a second.

Hero select shows "ASSEMBLE YOUR TEAM" with a countdown in the top-left corner, and right above
it the mode ("UNRANKED"), the side ("ATTACK") and the map name - all in big type. Seeing the
banner starts a match. The big "VICTORY!" / "DEFEAT" banner in the centre ends it; "PLAY OF THE
GAME", "VICTORY <MAP>" and the summary screen (top left) follow it as fallbacks.
Screen reading only, like the chat: never game memory.
"""

import logging
import time
from collections import deque
from collections.abc import Callable

import cv2
import numpy as np
from rapidfuzz import fuzz

from yaptracker import game_lists
from yaptracker.capture.source import Region, RelativeRegion

log = logging.getLogger(__name__)

# Measured on real 2560x1440 hero-select screenshots (#93), kept as fractions of the window.
HEROSELECT = RelativeRegion.from_pixels(Region(60, 330, 780, 60), 2560, 1440)
HEROSELECT_INFO = RelativeRegion.from_pixels(Region(60, 60, 780, 240), 2560, 1440)
# "PREPARE TO ATTACK 0:44" box, top centre: also at round starts, so only a backup (see below).
ROUND_START = RelativeRegion.from_pixels(Region(1080, 30, 400, 75), 2560, 1440)
ROUND_START_HEIGHT = 75  # px at 1440p, for has_bright_text
# "F1 HERO DETAILS", bottom left: a dark key cap and shadowed letters that HDR doesn't wash out
# (#300). Changing hero inside a match shows it too, so it only confirms a start (see below).
HERO_DETAILS = RelativeRegion.from_pixels(Region(40, 1355, 300, 60), 2560, 1440)
HERO_DETAILS_TEXT = "HERO DETAILS"
DETAILS_FRESH_S = 60.0  # a sighting this old still confirms a match the chat started
# The round-start box comes up to ~45 s after hero select ends: the info corner read at the last
# "HERO DETAILS" sighting this long ago is still this match's (#537).
DETAILS_CARRY_S = 90.0
# No "HERO DETAILS" this long: the next sighting is another screen (the Practice Range, the next
# hero select), read afresh. Above the in-match look interval, so one screen stays one (#537).
DETAILS_GAP_S = 12.0
# End of a match (#94): the centre banner, and the title strip in the top-left corner.
END_BANNER = RelativeRegion.from_pixels(Region(900, 590, 820, 250), 2560, 1440)
END_TITLE = RelativeRegion.from_pixels(Region(40, 30, 900, 75), 2560, 1440)
END_TITLE_HEIGHT = 75  # px at 1440p, for has_bright_text
OUTCOMES = {"VICTORY": "victory", "DEFEAT": "defeat", "DRAW": "draw"}
BANNER_TEXT = "ASSEMBLE YOUR TEAM"
MATCH = 80  # rapidfuzz ratio on the letters only; OCR may lose or swap a letter or two
# Queue names as Overwatch prints them above the map (the side, ATTACK/DEFEND, follows them).
REARM_S = 120  # the banner must be gone this long before a new hero select counts
IN_MATCH_EVERY_S = 5.0  # hero select looked for at most this often inside a running match
BETWEEN_EVERY_S = 2.0  # and between matches: the screen is up 20 s+, the start 1 s later at most
# The queue decides how chat is read since #331. Missed at the first look (a frame between
# animations, HDR glare): looked at again on later sightings of the banner, this often (#342).
# The map too (#378): Sessions shows it, and the mirror-round rule needs it (#364).
INFO_TRIES = 5


LOOK_BLOCK = 8  # px of a region per thumbnail pixel (#453)
SAME_LOOK = 12  # grey levels: the most any thumbnail pixel may differ to count as the same look
LOOKS_KEPT = 4  # per region size
# A kept read answers this many looks, then the region is read again: a misread of a still
# banner (glare, mid-animation) gets another chance, as do reads of an engine switched away from.
REUSES = 3


class SameLook:
    """A read of a signal region, done again only when the region looks different (#453).

    Between matches the menus stand still, and each look at them was a ~50 ms OCR read of the
    same picture. Each read is kept with a tiny grey thumbnail (one pixel per 8x8 block); a
    region whose every block is within SAME_LOOK of a kept one gets that read's text back. Text
    that appears or changes moves its blocks far more, so hero select and the end screen see the
    same text as before - only sooner, and after REUSES kept answers a real read again. The
    weakest banner read in Marv's start and end samples (washed out by HDR, 2026-11) still moves
    its blocks by 58 levels."""

    def __init__(self, read_line: Callable[[np.ndarray], str]) -> None:
        self._read_line = read_line
        self._kept: dict[tuple[int, ...], list[list]] = {}  # [thumbnail, text, looks left]
        self.reused = 0  # looks answered from what was kept (tools/signals_cost.py)

    def __call__(self, image: np.ndarray) -> str:
        thumb = _thumb(image)
        kept = self._kept.setdefault(image.shape, [])  # each region has its own size
        for i, entry in enumerate(kept):
            if int(np.abs(entry[0] - thumb).max()) <= SAME_LOOK:
                kept.pop(i)
                if entry[2]:
                    entry[2] -= 1
                    kept.insert(0, entry)
                    self.reused += 1
                    return entry[1]
                break  # used up: read afresh, below
        text = self._read_line(image)
        if text:  # an empty read isn't kept: the OCR model may still be loading (#219)
            kept.insert(0, [thumb, text, REUSES])
            del kept[LOOKS_KEPT:]
        return text


def _thumb(image: np.ndarray) -> np.ndarray:
    grey = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    size = (max(1, grey.shape[1] // LOOK_BLOCK), max(1, grey.shape[0] // LOOK_BLOCK))
    return cv2.resize(grey, size, interpolation=cv2.INTER_AREA).astype(np.int16)


def signal_regions(width: int, height: int) -> dict[str, Region]:
    return {
        "heroselect": HEROSELECT.to_pixels(width, height),
        "heroselect_info": HEROSELECT_INFO.to_pixels(width, height),
        "round_start": ROUND_START.to_pixels(width, height),
        "hero_details": HERO_DETAILS.to_pixels(width, height),
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


# The VICTORY! letters' pale gold (OpenCV hue 15-45, a little saturation, bright) fills this much
# of the banner crop: 0.13-0.28 on Marv's victory samples (full size), under 0.08 on every defeat,
# and 6 % of 233 other crops get there too: a wasted read every ~16 s, 0.3 % of a core (#555).
VICTORY_SHARE = 0.10
LOOKS_KEPT_S = 30  # banner looks remembered for the log line of an end without a result (#555)
RESULT_HELD_S = 600  # a result read this recently: a later end screen is still its match


def has_colour(image: np.ndarray, min_share: float = 0.08) -> bool:
    """Cheap check before reading the end banner: big, saturated letters fill a good part of it.

    DEFEAT follows the enemy colour setting, so any hue counts. VICTORY! is pale gold, too pale
    for that: it only passed on a colourful scene, and on a calm one no victory was ever read
    (#555: the outcome was unknown in up to half the matches). Its own colour counts too."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hue, sat, value = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    if float(((sat > 120) & (value > 170)).mean()) >= min_share:
        return True
    gold = (hue >= 15) & (hue <= 45) & (sat >= 25) & (sat <= 140) & (value >= 220)
    return float(gold.mean()) >= VICTORY_SHARE


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


def is_hero_details(text: str) -> bool:
    """The key hint, with or without its key: real 4K HDR reads "EHERO ETAILS", "HEROBETALS"
    (#300). Part of the text is enough, but never a lone word like "HERO"."""
    letters = _letters(text)
    return len(letters) >= 8 and fuzz.partial_ratio(_letters(HERO_DETAILS_TEXT), letters) >= MATCH


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
    if is_potg(letters):
        return True, None
    if fuzz.ratio(letters[:14], "SUMMARYREWARDS") >= MATCH:
        return True, None
    if found := _outcome_first(letters):
        return True, found[0]
    return False, None


def is_potg(letters: str) -> bool:
    """ "PLAY OF THE GAME" at the start of the title strip's letters."""
    return fuzz.ratio(letters[:13], "PLAYOFTHEGAME") >= 85


def title_map(text: str) -> str | None:
    """The map after the outcome in the title strip: "VICTORY ESPERANCA" -> Esperança (#383),
    matched against the game lists like hero select's."""
    found = _outcome_first(_letters(text))
    return game_lists.map_name(found[1]) if found else None


def _outcome_first(letters: str) -> tuple[str, str] | None:
    """(outcome, the letters after it) when the title starts with VICTORY, DEFEAT or DRAW."""
    for word, outcome in OUTCOMES.items():  # the map name follows the outcome
        if len(letters) > len(word) + 2 and fuzz.ratio(letters[: len(word)], word) >= 85:
            return outcome, letters[len(word) :]
    return None


def parse_info(lines: list[str]) -> tuple[str | None, str | None]:
    """(mode, map): the queue name from the top line, the map name from the bottom one.

    OCR reads e.g. ["UINRANKED ATTACK", "ESPERANCA"]: both are matched against the bundled
    game lists (#276); what matches nothing is none, never garbage like "INRONKED ALU9CK".
    """
    lines = [line.strip() for line in lines if line.strip()]
    if not lines:
        return None, None
    map_name = game_lists.map_name(lines[-1]) if len(lines) > 1 else None
    # glare may hide the queue line: then the side ("ATTACK") comes first (#537)
    for line in lines[:-1] if len(lines) > 1 else lines:
        if mode := game_lists.queue(line):
            return mode, map_name
    # a washed-out queue word: only on the top line, where the queue sits
    return game_lists.loose_queue(lines[0]), map_name


def _variants(image: np.ndarray):
    """The info corner as is, then two looks that keep white words on glare (#342): the
    inverted saturation (white text, coloured light) and the blue channel (white on yellow)."""
    yield image
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    yield cv2.merge([255 - hsv[:, :, 1]] * 3)
    yield cv2.merge([image[:, :, 0]] * 3)


# The queue title, top left of the info corner, as a share of its height and width (#554).
TITLE_BAND = (0.42, 0.70)


def read_title(read_line: Callable[[np.ndarray], str], image: np.ndarray | None) -> str | None:
    """The queue from the title alone (#554), read without text detection: on a bright map that
    loses the washed-out title altogether. As is, then its darkest channel: white letters stay
    white in all three, pink or cyan glare doesn't. Two ~10 ms reads."""
    if image is None or image.ndim != 3:
        return None
    height, width = image.shape[:2]
    band = np.ascontiguousarray(image[: int(height * TITLE_BAND[0]), : int(width * TITLE_BAND[1])])
    if band.size == 0:
        return None
    for look in (band, cv2.merge([band.min(axis=2)] * 3)):
        if mode := game_lists.title_queue(read_line(look)):
            return mode
    return None


def read_info(
    read_lines: Callable[[np.ndarray], list[str]],
    image: np.ndarray | None,
    read_line: Callable[[np.ndarray], str] | None = None,
):
    """(mode, map) of the info corner; the variants only while the queue or the map is still
    unknown. On Marv's 88 start samples they found 4 more queues and changed none that was
    read (#342); the map: OCR may read queue and map as one line ("UNRANKE MIDTOWN", #378)."""
    mode = map_name = None
    if image is None:
        return mode, map_name
    for variant in _variants(image):
        found_mode, found_map = parse_info(read_lines(np.ascontiguousarray(variant)))
        mode, map_name = mode or found_mode, map_name or found_map
        if mode and map_name:
            break
    if mode is None and read_line is not None:
        mode = read_title(read_line, image)
    return mode, map_name


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
        adoptable: Callable[[], bool] = lambda: False,
        on_info: Callable[[str | None, str | None], None] = lambda mode, map_name: None,
        read_band: Callable[[np.ndarray], str] | None = None,
    ) -> None:
        self._read_line, self._read_lines, self._on_info = read_line, read_lines, on_info
        # the title band alone, read afresh, never a kept read (#453, #554); None: not read
        self._read_band = read_band
        self._info_left = 0  # later full looks at the info corner while it's unread (#342)
        self._known: tuple[str | None, str | None] = (None, None)
        self._match_running, self._adoptable = match_running, adoptable
        self._on_start, self._clock, self._rearm_s = on_start, clock, rearm_s
        self._active = False
        self._last_seen = 0.0
        self._read_at = -IN_MATCH_EVERY_S  # the last banner read (#303)
        self._details_at: float | None = None  # "HERO DETAILS" seen without the banner (#300)
        self._details_info: tuple[str | None, str | None] = (None, None)
        self._details_left = 0  # more looks at the corner while it's unread (#537)

    def update(self, signals: dict[str, np.ndarray]) -> None:
        strip = signals.get("heroselect")
        if strip is None:
            return
        now = self._clock()
        if self._confirm(now):
            return
        # Hero select is on screen 20 s and more, and inside a running match it can only come
        # after its end: one look every few seconds finds it. The gate passes on most frames,
        # and each pass is a ~50 ms read (#303: 3.0 % of a core before, 1 read a second).
        every = IN_MATCH_EVERY_S if self._match_running() else BETWEEN_EVERY_S
        if now - self._read_at < every:
            if self._active and now - self._last_seen >= self._rearm_s:
                self._active = False
            return
        # The strip is one line: cheap pixel check first, then a fast single-line read.
        seen = False
        if has_bright_text(strip):
            self._read_at = now
            seen = is_banner(self._read_line(strip))
        if seen:
            self._last_seen = now
            if not self._active:
                self._active, self._details_at = True, None  # its own corner, read just below
                info = signals.get("heroselect_info")
                self._known = read_info(self._read_lines, info, self._read_band)
                self._info_left = INFO_TRIES if None in self._known else 0
                self._on_start(*self._known)
            elif self._info_left or self._known[0] is None:  # the queue: all hero select long
                self._look_again(signals.get("heroselect_info"))
            return
        self._look_for_details(signals, now)
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
            # glare hid the banner, not hero select: its corner was read at "HERO DETAILS" (#537)
            fresh = self._details_at is not None and now - self._details_at <= DETAILS_CARRY_S
            self._known = self._details_info if fresh else (None, None)
            self._details_at = None
            self._on_start(*self._known)
        elif self._active and now - self._last_seen >= self._rearm_s:
            self._active = False

    def _look_again(self, info: np.ndarray | None) -> None:
        """Hero select is still up and its queue or map unknown: another look (#342, #378). The
        map a few times; the queue every sighting until it's read, as the camera moves and the
        glare with it (#554) - after the full looks only the cheap title read."""
        mode = map_name = None
        if self._info_left:
            self._info_left -= 1
            mode, map_name = read_info(self._read_lines, info, self._read_band)
        elif self._read_band is not None:
            mode = read_title(self._read_band, info)
        known = (self._known[0] or mode, self._known[1] or map_name)
        if known != self._known:
            self._known = known
            self._on_info(*known)
        if None not in known:
            self._info_left = 0

    def _look_for_details(self, signals: dict[str, np.ndarray], now: float) -> None:
        """On a bright map HDR washes the banner out to white on white, but not the key hint
        "F1 HERO DETAILS" at the bottom (#300). Changing hero in a match or the Practice Range
        shows it too, so it never starts a match: it only confirms one the chat starts."""
        box = signals.get("hero_details")
        if self._active or box is None or (self._match_running() and not self._adoptable()):
            return
        if not has_bright_text(box):
            return
        self._read_at = now
        if not is_hero_details(self._read_line(box)):
            return
        # A new screen is read afresh, never filled in from a menu's corner; washed out, it gets
        # a few more looks while it stays up (#537)
        if self._details_at is None or now - self._details_at > DETAILS_GAP_S:
            self._details_info, self._details_left = (None, None), 1 + INFO_TRIES
        info = signals.get("heroselect_info")
        if info is not None and None in self._details_info and self._details_left:
            self._details_left -= 1
            mode, map_name = read_info(self._read_lines, info, self._read_band)
            self._details_info = (self._details_info[0] or mode, self._details_info[1] or map_name)
        self._details_at = now

    def _confirm(self, now: float) -> bool:
        """A match the chat started takes the hero select seen just before or after it."""
        if (
            self._active
            or self._details_at is None
            or now - self._details_at > DETAILS_FRESH_S
            or not self._adoptable()
        ):
            return False
        self._active, self._last_seen, self._details_at = True, now, None
        # "HERO DETAILS" also shows on menus (role select, the map vote): the hero select seen
        # after it still gets its info corner read (#378)
        self._known = self._details_info
        self._info_left = INFO_TRIES if None in self._known else 0
        self._on_start(*self._details_info)
        return True


class EndScreen:
    """Calls on_end(outcome) once per match end, and again if the outcome only shows up later;
    on_map(map) once when the title strip names the map (#383)."""

    def __init__(
        self,
        read_line: Callable[[np.ndarray], str],
        on_end: Callable[[str | None], None],
        clock: Callable[[], float] = time.monotonic,
        rearm_s: float = REARM_S,
        title_every_s: float = 3.0,
        on_map: Callable[[str], None] = lambda map_name: None,
    ) -> None:
        self._read_line, self._on_end, self._clock = read_line, on_end, clock
        self._rearm_s, self._title_every_s, self._on_map = rearm_s, title_every_s, on_map
        self._active = False
        self._map_said = False
        self._outcome: str | None = None
        self._last_seen = 0.0
        self._title_read = float("-inf")
        self._looks: deque[tuple[float, bool]] = deque()  # banner looks: (when, coloured?)
        self._result_at = float("-inf")  # the last result read (#555)

    def update(self, signals: dict[str, np.ndarray]) -> None:
        now = self._clock()
        seen, outcome, map_name, text = False, None, None, ""
        banner = signals.get("end_banner")
        # The banner is up for ~4 s: read it every second, unless the outcome is known already.
        if banner is not None and self._outcome is None:
            coloured = has_colour(banner)
            self._remember_look(now, coloured)
            if coloured:
                outcome = banner_outcome(self._read_line(banner))
                seen = outcome is not None
        # The title screens stay for 10+ s each: every few seconds is plenty.
        title = signals.get("end_title")
        if not seen and title is not None and now - self._title_read >= self._title_every_s:
            self._title_read = now
            if has_bright_text(title, height_1440=END_TITLE_HEIGHT):
                text = self._read_line(title)
                (seen, outcome), map_name = title_end(text), title_map(text)
        if seen:
            self._last_seen = now
            if not self._active and outcome is None:
                self._why_no_result(text, now)
            if outcome:
                self._result_at = now
                self._looks.clear()
            if not self._active or (outcome and not self._outcome):
                self._active, self._outcome = True, self._outcome or outcome
                self._on_end(outcome)
            if map_name and not self._map_said:  # after on_end: the match is over by then
                self._map_said = True
                self._on_map(map_name)
        elif self._active and now - self._last_seen >= self._rearm_s:
            self._active, self._outcome, self._map_said = False, None, False

    def _remember_look(self, now: float, coloured: bool) -> None:
        self._looks.append((now, coloured))
        self._trim(now)

    def _trim(self, now: float) -> None:
        while self._looks and now - self._looks[0][0] > LOOKS_KEPT_S:
            self._looks.popleft()

    def _why_no_result(self, title: str, now: float) -> None:
        """The match is over by a later screen, the result never read: the log says why, so an
        evening's misses can be told apart (#555) - the banner never looked at (no pictures),
        never coloured enough to read, or read as something else. No read text: names."""
        if now - self._result_at < RESULT_HELD_S:
            return  # the result was read: this is its summary seen again after a while
        self._trim(now)
        coloured = sum(c for _, c in self._looks)
        screen = "PLAY OF THE GAME" if is_potg(_letters(title)) else "the summary"
        log.info("end screen: match over (%s), no result read: %d look(s) at the banner in "
                 "the %d s before, %d coloured enough to read, none read as a result", screen,
                 len(self._looks), LOOKS_KEPT_S, coloured)  # fmt: skip

"""Reading per kind of match (#330, #331). Void's FPS test: the chat reading is what costs the game,
not the capture. So the reader is picked for the running match by its queue, which hero select
read (#276): Competitive is one choice, every other match the other one. Between matches the
game is idle, so the chat is always read with the best quality then.

- best: the chosen engine of the calibration preview, RapidOCR unless it won't start
- light: Windows OCR, ~10x cheaper and not AVX-heavy; misses some lines and words, so the match
  is read again with the best quality once the game is idle (#336)
- after: no reading during the match; its changed chat frames are read once it's over (#335)
"""

import logging
import threading
from collections import Counter
from collections.abc import Callable

import numpy as np

from yaptracker.ocr import engine as ocr
from yaptracker.ocr.engine import OcrLine, OcrUnavailable

log = logging.getLogger(__name__)

BEST, LIGHT, AFTER = "best", "light", "after"
COMPETITIVE_QUEUES = frozenset({"COMPETITIVE", "GEWERTET"})  # game_lists.queue names (#276)
LIGHT_ENGINE = ocr.WindowsOcrEngine.name
CHOICES = (AFTER, LIGHT, BEST)
DEFAULT_COMPETITIVE = AFTER  # Marv + Void (#330): ranked must be smooth
DEFAULT_OTHER = BEST


def competitive(queue: str | None) -> bool:
    return queue in COMPETITIVE_QUEUES


class ReadingMode:
    """Picks the reader for every chat read and counts which mode ran, for the log line."""

    def __init__(
        self,
        matches: Callable[[], object | None],
        for_competitive: Callable[[], str],
        for_other: Callable[[], str],
        best_engine: Callable[[], str],
        get: Callable[[str], object] = ocr.get,
        available: Callable[[], list[str]] = ocr.available,
    ) -> None:
        self._matches, self._competitive, self._other = matches, for_competitive, for_other
        self._best, self._get, self._available = best_engine, get, available
        self._lock = threading.Lock()
        self._counts: Counter[str] = Counter()
        self.light_problem: str | None = None  # why light reading can't run here, for Settings
        self._said: tuple | None = None  # the mode the log said last

    def now(self) -> str:
        """The mode for a read right now: by the running match's queue, best between matches."""
        tracker = self._matches()
        if tracker is None or not tracker.running:
            mode, why = BEST, "between matches"
        elif competitive(tracker.match_mode):
            mode, why = self._competitive(), f"Competitive, match {tracker.match_id}"
        else:
            mode, why = self._other(), f"{tracker.match_mode or 'queue unknown'}, match " \
                f"{tracker.match_id}"  # fmt: skip
        with self._lock:
            said, self._said = self._said, (mode, why)
        if said != (mode, why):
            log.info("reading: %s (%s)", mode, why)  # which mode ran, for Void's FPS check
        return mode

    def engine(self, mode: str):
        """(mode that really runs, engine). Light falls back to best where Windows OCR can't;
        frames kept for after the match are read with the best quality."""
        if mode == LIGHT and self.light_problem is None:
            if LIGHT_ENGINE not in self._available():
                self._no_light("Windows OCR only runs on Windows")
            else:
                try:
                    return LIGHT, self._get(LIGHT_ENGINE)
                except OcrUnavailable as reason:
                    self._no_light(str(reason))
        return BEST, self._get(self._best())

    def read(self, image: np.ndarray, scale: float, mode: str | None = None) -> list[OcrLine]:
        """Read with the mode for right now, or the one a kept frame was seen with."""
        asked = self.now() if mode is None else mode
        ran, engine = self.engine(asked)
        with self._lock:
            self._counts[AFTER if asked == AFTER else ran] += 1  # "after 40": read after a match
        return engine.read(image, scale=scale)

    def take_counts(self) -> str:
        """Which mode read how many frames since the last call: "light 31, best 9"."""
        with self._lock:
            counts, self._counts = self._counts, Counter()
        return ", ".join(f"{mode} {n}" for mode, n in counts.most_common())

    def _no_light(self, reason: str) -> None:
        self.light_problem = reason
        log.warning("light reading can't run here (%s): reading with the best quality", reason)

"""Reading per kind of match (#330, #331). Void's FPS test: the chat reading is what costs the game,
not the capture. So the reader is picked for the running match by its queue, which hero select
read (#276): Competitive is one choice, every other match the other one. Between matches the
game is idle, so the chat is always read with the best quality then.

- best: the chosen engine of the calibration preview, RapidOCR unless it won't start
- light: Windows OCR, ~10x cheaper and not AVX-heavy; misses some lines and words
- after: read after the match (#332, not built yet: hidden, Competitive reads light until then)
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
LIVE_CHOICES = (LIGHT, BEST)  # what Settings offers until #332 builds "after"
DEFAULT_COMPETITIVE = LIGHT  # AFTER once #332 is in
DEFAULT_OTHER = BEST


def competitive(queue: str | None) -> bool:
    return queue in COMPETITIVE_QUEUES


def live(choice: str) -> str:
    """The choice as it reads today: "after" isn't built yet, so it reads light (#331)."""
    return choice if choice in LIVE_CHOICES else LIGHT


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

    def now(self) -> str:
        """The mode for a read right now: by the running match's queue, best between matches."""
        tracker = self._matches()
        if tracker is None or not tracker.running:
            return BEST
        choice = self._competitive() if competitive(tracker.match_mode) else self._other()
        return live(choice)

    def engine(self, mode: str):
        """(mode that really runs, engine). Light falls back to best where Windows OCR can't."""
        if mode == LIGHT and self.light_problem is None:
            if LIGHT_ENGINE not in self._available():
                self._no_light("Windows OCR only runs on Windows")
            else:
                try:
                    return LIGHT, self._get(LIGHT_ENGINE)
                except OcrUnavailable as reason:
                    self._no_light(str(reason))
        return BEST, self._get(self._best())

    def read(self, image: np.ndarray, scale: float) -> list[OcrLine]:
        mode, engine = self.engine(self.now())
        with self._lock:
            self._counts[mode] += 1
        return engine.read(image, scale=scale)

    def take_counts(self) -> str:
        """Which mode read how many frames since the last call: "light 31, best 9"."""
        with self._lock:
            counts, self._counts = self._counts, Counter()
        return ", ".join(f"{mode} {n}" for mode, n in counts.most_common())

    def _no_light(self, reason: str) -> None:
        self.light_problem = reason
        log.warning("light reading can't run here (%s): reading with the best quality", reason)

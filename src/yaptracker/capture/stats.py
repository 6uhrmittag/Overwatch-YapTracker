"""What the capture really delivers (#187): frames per second from Windows vs. what we asked
for, and the time each frame costs in YapTracker's own callback. Once a minute in the log, and
live in Settings -> About."""

import collections
import logging
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)


class CaptureStats:
    def __init__(self, asked_fps: float = 4.0, clock: Callable[[], float] = time.monotonic,
                 log_every_s: float = 60.0) -> None:  # fmt: skip
        self.asked_fps, self._clock, self._log_every_s = asked_fps, clock, log_every_s
        self._lock = threading.Lock()
        self._recent: collections.deque[float] = collections.deque()  # arrival times, last 10 s
        self._minute_start: float | None = None
        self._minute_frames, self._minute_spent, self._minute_skipped = 0, 0.0, 0
        self.cannot: list[str] = []  # what this Windows can't do for the capture (#216)
        self.how = "WGC"  # or "GDI, chat box only" without the rate setting (#248)

    def skipped(self) -> None:
        """A frame arrived too soon after the last one and was let go untouched (#216)."""
        now = self._clock()
        with self._lock:
            self._arrived(now)
            self._minute_skipped += 1

    def frame(self, spent_s: float) -> None:
        """A frame arrived from Windows; our callback spent `spent_s` on it."""
        now = self._clock()
        with self._lock:
            self._arrived(now)
            self._minute_frames += 1
            self._minute_spent += spent_s
            elapsed = now - self._minute_start
            if elapsed < self._log_every_s:
                return
            used, skipped = self._minute_frames, self._minute_skipped
            rate, per_frame = (used + skipped) / elapsed, self._minute_spent / used
            self._minute_start, self._minute_frames, self._minute_spent = now, 0, 0.0
            self._minute_skipped = 0
        extra = f", {skipped / elapsed:.1f}/s of them skipped" if skipped else ""
        source = "from Windows" if self.how == "WGC" else f"by {self.how}"
        log.info("capture: %.1f frames/s %s (asked for %g), %.1f ms per frame here%s",
                 rate, source, self.asked_fps, per_frame * 1000, extra)  # fmt: skip

    def _arrived(self, now: float) -> None:
        self._recent.append(now)
        while self._recent and now - self._recent[0] > 10:
            self._recent.popleft()
        if self._minute_start is None:
            self._minute_start = now

    def per_second(self) -> float | None:
        """Frames per second over the last 10 s; None when nothing arrived lately."""
        now = self._clock()
        with self._lock:
            recent = [t for t in self._recent if now - t <= 10]
        if len(recent) < 2:
            return None
        return (len(recent) - 1) / max(1e-6, recent[-1] - recent[0])


CAPTURE = CaptureStats()

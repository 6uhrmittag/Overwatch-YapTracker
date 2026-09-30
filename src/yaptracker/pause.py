"""Pause (#20): captured frames are dropped, nothing is kept. It ends by itself.

Forgetting to resume must cost one match at most. Until match detection (#21) can call
next_match_started(), a pause ends after INTERIM_S, about one match.
"""

import threading
import time
from collections.abc import Callable

INTERIM_S = 15 * 60


class Pause:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()  # toggled from the hotkey thread, read by capture and UI
        self._until: float | None = None

    @property
    def paused(self) -> bool:
        with self._lock:
            if self._until is not None and self._clock() >= self._until:
                self._until = None
            return self._until is not None

    def remaining_s(self) -> float:
        with self._lock:
            return max(0.0, self._until - self._clock()) if self._until is not None else 0.0

    def pause(self) -> None:
        with self._lock:
            self._until = self._clock() + INTERIM_S

    def resume(self) -> None:
        with self._lock:
            self._until = None

    def toggle(self) -> None:
        self.resume() if self.paused else self.pause()

    def next_match_started(self) -> None:
        """Called by match detection (#21): a new match means recording again."""
        self.resume()

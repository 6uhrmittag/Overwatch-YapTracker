"""Capture health (#75): every stretch where Overwatch ran but nothing was recorded is a gap.

Gaps are stored in capture_gaps, never silent holes:
- crash        capture raised an error (it is retried with backoff)
- no_frames    the window was there but no picture came for 10 s (the capture is restarted)
- window_lost  the capture ended but the Overwatch window is still there
- paused       the user paused (#20)
If Overwatch itself closes, nothing is being lost, so an open gap ends there.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from yaptracker.store.repo import Store


@dataclass(frozen=True)
class Gap:
    id: int
    reason: str
    since: float


class CaptureHealth:
    def __init__(self, store: Store, clock: Callable[[], float] = time.time) -> None:
        self._store, self._clock = store, clock
        self._lock = threading.Lock()
        self.gap: Gap | None = None
        self.last_frame_at: float | None = None

    def frame(self) -> None:
        """A picture arrived: recording again, unless paused."""
        with self._lock:
            self.last_frame_at = self._clock()
            if self.gap is not None and self.gap.reason != "paused":
                self._close()

    def lost(self, reason: str) -> None:
        """Capture broke; the gap starts at the last picture we had. The first reason wins."""
        with self._lock:
            if self.gap is None:
                since = self.last_frame_at or self._clock()
                self.gap = Gap(self._store.open_gap(since, reason), reason, since)

    def paused(self, on: bool) -> None:
        with self._lock:
            is_paused = self.gap is not None and self.gap.reason == "paused"
            if on and not is_paused:
                if self.gap is not None:
                    self._close()
                now = self._clock()
                self.gap = Gap(self._store.open_gap(now, "paused"), "paused", now)
            elif not on and is_paused:
                self._close()

    def game_closed(self) -> None:
        """Overwatch is gone: nothing more is being lost."""
        with self._lock:
            if self.gap is not None:
                self._close()

    stop = game_closed  # app shutdown: close what's open

    def _close(self) -> None:
        self._store.close_gap(self.gap.id, self._clock())
        self.gap = None

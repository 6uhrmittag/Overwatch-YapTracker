"""Capture health (#75): every stretch where Overwatch ran but nothing was recorded is a gap.

Gaps are stored in capture_gaps, never silent holes:
- crash        capture raised an error (it is retried with backoff)
- no_frames    the window was there but no picture came for 10 s (the capture is restarted)
- window_lost  the capture ended but the Overwatch window is still there
- paused       the user paused (#20)
- app_not_running  Overwatch already ran when YapTracker started (#99)
If Overwatch itself closes, nothing is being lost, so an open gap ends there.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from yaptracker.store.repo import Store

log = logging.getLogger(__name__)
# Starting YapTracker a few seconds after the game isn't worth a gap.
MIN_MISSED_S = 30.0


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
                log.warning("not recording since %s: %s", _clock_time(since), reason)

    def paused(self, on: bool) -> None:
        with self._lock:
            is_paused = self.gap is not None and self.gap.reason == "paused"
            if on and not is_paused:
                if self.gap is not None:
                    self._close()
                now = self._clock()
                self.gap = Gap(self._store.open_gap(now, "paused"), "paused", now)
                log.info("paused")
            elif not on and is_paused:
                self._close()

    def game_closed(self) -> None:
        """Overwatch is gone: nothing more is being lost."""
        with self._lock:
            if self.gap is not None:
                self._close()

    stop = game_closed  # app shutdown: close what's open

    def started_late(self, game_started_at: float | None, last_activity: float | None) -> None:
        """Overwatch already ran at app start: what happened since then wasn't recorded.

        The gap starts when the game started, or when YapTracker last recorded something
        (a restart mid-evening only loses the time it was gone).
        """
        if game_started_at is None:
            log.info("Overwatch was already running; its start time is unknown, no gap stored")
            return
        with self._lock:
            now = self._clock()
            since = max(game_started_at, last_activity or game_started_at)
            if now - since < MIN_MISSED_S:
                return
            self._store.close_gap(self._store.open_gap(since, "app_not_running"), now)
            log.warning("not recorded from %s: YapTracker wasn't running", _clock_time(since))

    def _close(self) -> None:
        now = self._clock()
        self._store.close_gap(self.gap.id, now)
        log.info("recording again after %.0f s (%s)", now - self.gap.since, self.gap.reason)
        self.gap = None


def _clock_time(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))

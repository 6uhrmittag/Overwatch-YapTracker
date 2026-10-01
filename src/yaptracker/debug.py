"""Debug samples (#63): YapTracker keeps the moments it found hard, so they become tests later.

data\\debug\\<date>\\<time>-<what>\\ holds JPEG overview frames (every 4th pixel of the game
window) and the PNG signal crops the detectors read. Real names are in there: like
fixtures/private/, never committed and never uploaded (YapTracker is local-only anyway).
At most 1 GB and 14 days, the oldest samples go first. Nothing is kept while paused.
"""

import shutil
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

# A missed end screen only shows when the next match starts (hero select, or chat after the
# 5-minute gap), so the overview frames of the last few minutes are kept to look back at it.
BUFFER_S = 6 * 60
CAP_BYTES = 1_000_000_000
KEEP_DAYS = 14


def folder_size(folder: Path) -> int:
    if not folder.exists():
        return 0
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())


class DebugSamples:
    def __init__(
        self,
        folder: Path,
        enabled: Callable[[], bool],
        clock: Callable[[], float] = time.time,
        buffer_s: float = BUFFER_S,
        cap_bytes: int = CAP_BYTES,
        keep_days: int = KEEP_DAYS,
    ) -> None:
        self._folder, self._enabled, self._clock = folder, enabled, clock
        self._buffer_s, self._cap_bytes, self._keep_days = buffer_s, cap_bytes, keep_days
        self._lock = threading.Lock()
        self._overviews: deque[tuple[float, bytes]] = deque()
        self._signals: dict[str, np.ndarray] = {}

    def on_signals(self, signals: dict[str, np.ndarray], paused: bool = False) -> None:
        """About once a second from the capture thread: signal crops, every few s an overview."""
        if paused or not self._enabled():
            with self._lock:
                self._overviews.clear()
                self._signals = {}
            return
        now = self._clock()
        overview = signals.get("overview")
        jpg = None
        if overview is not None:
            ok, encoded = cv2.imencode(".jpg", overview, [cv2.IMWRITE_JPEG_QUALITY, 80])
            jpg = encoded.tobytes() if ok else None
        with self._lock:
            self._signals = {k: v for k, v in signals.items() if k != "overview"}
            if jpg is not None:
                self._overviews.append((now, jpg))
            while self._overviews and now - self._overviews[0][0] > self._buffer_s:
                self._overviews.popleft()

    def match_event(self, what: str) -> Path | None:
        """'start' / 'end': the newest overview and crops. 'missed-end': every buffered overview."""
        if not self._enabled():
            return None
        with self._lock:
            overviews = list(self._overviews)
            signals = dict(self._signals)
        if what != "missed-end":
            overviews = overviews[-1:]
        if not overviews and not signals:
            return None
        now = time.localtime(self._clock())
        sample = self._folder / time.strftime("%Y-%m-%d", now)
        sample /= f"{time.strftime('%H-%M-%S', now)}-{what}"
        sample.mkdir(parents=True, exist_ok=True)
        for ts, jpg in overviews:
            (sample / f"{time.strftime('%H-%M-%S', time.localtime(ts))}.jpg").write_bytes(jpg)
        for name, crop in signals.items():
            cv2.imwrite(str(sample / f"{name}.png"), crop)
        self.clean_up()
        return sample

    def clean_up(self) -> None:
        """Day folders older than 14 days go, then the oldest samples until under the cap."""
        if not self._folder.exists():
            return
        oldest_kept = time.strftime(
            "%Y-%m-%d", time.localtime(self._clock() - self._keep_days * 86400)
        )
        days = sorted(p for p in self._folder.iterdir() if p.is_dir())
        for day in days:
            if day.name < oldest_kept:
                shutil.rmtree(day)
        samples = sorted(s for day in days if day.exists() for s in day.iterdir() if s.is_dir())
        sizes = {s: folder_size(s) for s in samples}
        total = sum(sizes.values())
        for sample in samples:  # names sort by date, then time
            if total <= self._cap_bytes:
                break
            shutil.rmtree(sample)
            total -= sizes[sample]
        for day in days:
            if day.exists() and not any(day.iterdir()):
                day.rmdir()

    def size_bytes(self) -> int:
        return folder_size(self._folder)

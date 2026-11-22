"""Line pictures (#120): the picture of every stored chat line, so emoji and icons are kept.

data\\lines\\<yyyy-mm>\\<message id>.webp, lossless and in colour, cut from the very frame the
stored reading came from. Lossless WebP rather than PNG: real lines with the game behind them
are ~8 kB instead of ~11 kB (measured, #120). OCR can't spell a heart; the picture still
shows it. Local only, like the database. At most 2 GB by default: the oldest months go first;
the month being written never goes as a whole, only its oldest pictures (#462).
"""

import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from yaptracker import images
from yaptracker.capture.source import Region
from yaptracker.sizes import FolderSizes

CAP_BYTES = 2_000_000_000
PAD = 2  # px above and below the line's box, so outlines stay whole


def row(image: np.ndarray, box: Region) -> np.ndarray:
    """A line's picture: the whole row across the chat box (#259). One OCR box can stop short
    of the channel icon, the first letters of a name or a trailing icon the text marks."""
    y0, y1 = max(0, box.y - PAD), min(image.shape[0], box.y + box.height + PAD)
    return image[y0:y1, :]


def pictures_in(folder: Path) -> list[tuple[Path, int]]:
    """Every picture and its size: the one walk, at start (#387)."""
    if not folder.exists():
        return []
    return [(f, f.stat().st_size) for f in folder.rglob("*.webp")]


RETRY_S = 60.0  # still over the cap after a clean-up (a picture open somewhere): wait (#462)
DAY_S = 86_400


class LinePictures:
    def __init__(
        self,
        folder: Path,
        enabled: Callable[[], bool] = lambda: True,
        cap_bytes: int = CAP_BYTES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._folder, self._enabled, self._cap_bytes = folder, enabled, cap_bytes
        self._clock = clock
        self._cleaning = threading.Lock()  # one clean-up at a time
        # Saves wait only while a month is being marked for deletion, never for the delete
        # itself (#462): a save into a month on its way out is skipped, it would go anyway.
        self._lock = threading.Lock()
        self._deleting: set[str] = set()
        self._last_month: str | None = None  # the month the last picture went into
        self._retry_at = 0.0
        self.sizes = FolderSizes()  # counted once, then kept up to date (#387)

    def path(self, message_id: int, ts: float) -> Path:
        return self._folder / time.strftime("%Y-%m", time.localtime(ts)) / f"{message_id}.webp"

    def save(self, message_id: int, ts: float, image: np.ndarray, box: Region) -> Path | None:
        """The line's picture; a better reading later saves over it."""
        if not self._enabled():
            return None
        crop = row(image, box)
        if crop.size == 0:
            return None
        target = self.path(message_id, ts)
        with self._lock:
            if target.parent.name in self._deleting:
                return None
            target.parent.mkdir(parents=True, exist_ok=True)
            # Next to it first: a full disk leaves no broken picture, nor an older good one (#452)
            part = target.with_name(f"{target.stem}.part.webp")
            try:
                images.write(part, crop, [cv2.IMWRITE_WEBP_QUALITY, 101])  # > 100: lossless
            except OSError:
                part.unlink(missing_ok=True)
                raise
            part.replace(target)
            self.sizes.set(target, target.stat().st_size)  # over an older one: the difference
            self._last_month = target.parent.name
        total = self.sizes.total()
        if total is not None and total > self._cap_bytes and self._clock() >= self._retry_at:
            self.clean_up()
        return target

    def start(self, background: bool = True) -> None:
        """At start: count the folder once in the background, then clean up."""
        self.sizes.count(lambda: pictures_in(self._folder), self.clean_up, background)

    def _kept_months(self) -> set[str]:
        """Months that never go as a whole (#462): this one and yesterday's (an evening past
        midnight), the one the last picture went into, and the newest folder."""
        now = self._clock()
        kept = {time.strftime("%Y-%m", time.localtime(t)) for t in (now, now - DAY_S)}
        return kept | ({self._last_month} if self._last_month else set())

    def clean_up(self) -> None:
        """Oldest months first until under the cap; the months being written only lose their
        oldest pictures, never the newest one (#462). Not before the folder is counted."""
        if not self.sizes.ready.is_set() or not self._folder.exists():
            return
        with self._cleaning:
            months, files = _order(self.sizes.snapshot(), self._kept_months())
            for name in months:
                if (self.sizes.total() or 0) <= self._cap_bytes:
                    break
                month = self._folder / name
                with self._lock:  # a save into it that has begun ends first
                    self._deleting.add(name)
                try:
                    shutil.rmtree(month, ignore_errors=True)
                    self.sizes.drop(month)
                    for left, size in pictures_in(month):  # couldn't go (open somewhere)
                        self.sizes.set(left, size)
                finally:
                    with self._lock:
                        self._deleting.discard(name)
            for picture in files:  # one by one: a stuck one is made up for by the next
                if (self.sizes.total() or 0) <= self._cap_bytes:
                    break
                try:
                    picture.unlink(missing_ok=True)
                except OSError:  # open somewhere: stays, and stays counted
                    continue
                self.sizes.drop(picture)
            over = (self.sizes.total() or 0) > self._cap_bytes
            self._retry_at = self._clock() + RETRY_S if over else 0.0

    def size_bytes(self) -> int | None:
        """None while it's still being counted at start."""
        return self.sizes.total()

    @property
    def cap_bytes(self) -> int:
        return self._cap_bytes

    def set_cap(self, cap_bytes: int) -> None:
        """Settings' slider (#389); clean_up() then deletes what's over it, raising deletes
        nothing."""
        self._cap_bytes = cap_bytes
        self._retry_at = 0.0

    def would_free(self, cap_bytes: int) -> tuple[int, str | None, bool, bool]:
        """What a cap of `cap_bytes` would delete, as clean_up() does it: (bytes, the oldest
        month kept, "2026-10" (None: no pictures), whether older months go whole, whether the
        kept months lose their oldest pictures). From the tally, no walking."""
        sizes = self.sizes.snapshot()
        months, files = _order(sizes, self._kept_months())
        left, gone_months, trimmed = sum(sizes.values()), set(), False
        by_month: dict[str, int] = {}
        for unit, size in sizes.items():
            by_month[unit.parent.name] = by_month.get(unit.parent.name, 0) + size
        for name in months:
            if left <= cap_bytes:
                break
            gone_months.add(name)
            left -= by_month[name]
        for picture in files:
            if left <= cap_bytes:
                break
            trimmed, left = True, left - sizes[picture]
        kept = sorted(set(by_month) - gone_months)
        freed = sum(sizes.values()) - left
        return freed, (kept[0] if kept else None), bool(gone_months), trimmed


def _id(picture: Path) -> int:
    """A picture's message id: the order lines were stored in. A leftover ".part" first."""
    return int(picture.stem) if picture.stem.isdigit() else -1


def _order(sizes: dict[Path, int], kept: set[str]) -> tuple[list[str], list[Path]]:
    """In what order pictures may go (#462): whole months, oldest first, except the kept ones
    and the newest folder; then the kept months' pictures, oldest first, never the newest."""
    names = sorted({unit.parent.name for unit in sizes})
    kept = kept | set(names[-1:])
    months = [name for name in names if name not in kept]
    pictures = sorted((u for u in sizes if u.parent.name in kept), key=lambda u: (_id(u), u))
    return months, pictures[:-1]

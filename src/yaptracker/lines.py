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


def pictures_in(folder: Path) -> list[tuple[Path, int]]:
    """Every picture and its size: the one walk, at start (#387)."""
    if not folder.exists():
        return []
    return [(f, f.stat().st_size) for f in folder.rglob("*.webp")]


class LinePictures:
    def __init__(
        self,
        folder: Path,
        enabled: Callable[[], bool] = lambda: True,
        cap_bytes: int = CAP_BYTES,
    ) -> None:
        self._folder, self._enabled, self._cap_bytes = folder, enabled, cap_bytes
        self._lock = threading.Lock()  # a save or a clean-up at a time (#462)
        self.sizes = FolderSizes()  # counted once, then kept up to date (#387)

    def path(self, message_id: int, ts: float) -> Path:
        return self._folder / time.strftime("%Y-%m", time.localtime(ts)) / f"{message_id}.webp"

    def save(self, message_id: int, ts: float, image: np.ndarray, box: Region) -> Path | None:
        """The line's picture; a better reading later saves over it."""
        if not self._enabled():
            return None
        h, w = image.shape[:2]
        # The whole row across the chat box (#259): one OCR box can stop short of the channel
        # icon, the first letters of a name or a trailing icon the text marks with "◇".
        y0, y1 = max(0, box.y - PAD), min(h, box.y + box.height + PAD)
        crop = image[y0:y1, :]
        if crop.size == 0:
            return None
        target = self.path(message_id, ts)
        with self._lock:  # a clean-up from Settings can't delete the folder mid-write (#462)
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
        total = self.sizes.total()
        if total is not None and total > self._cap_bytes:
            self.clean_up()
        return target if target.exists() else None

    def start(self, background: bool = True) -> None:
        """At start: count the folder once in the background, then clean up."""
        self.sizes.count(lambda: pictures_in(self._folder), self.clean_up, background)

    def clean_up(self) -> None:
        """Oldest months first until under the cap; the newest month only ever loses its oldest
        pictures, never its newest (#462). Not before the folder is counted."""
        if not self.sizes.ready.is_set() or not self._folder.exists():
            return
        with self._lock:
            months, files = _plan(self.sizes.snapshot(), self._cap_bytes)
            for name in months:
                month = self._folder / name
                shutil.rmtree(month, ignore_errors=True)
                self.sizes.drop(month)
                for left, size in pictures_in(month):  # couldn't go (open somewhere): counted
                    self.sizes.set(left, size)
            for picture in files:
                try:
                    picture.unlink(missing_ok=True)
                except OSError:  # open somewhere: stays, and stays counted
                    continue
                self.sizes.drop(picture)

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

    def would_free(self, cap_bytes: int) -> tuple[int, str | None, bool]:
        """What a cap of `cap_bytes` would delete, as clean_up() does it: (bytes, the oldest
        month kept, "2026-10" (None: no pictures), whether that month loses its oldest pictures
        too). From the tally, no walking."""
        sizes = self.sizes.snapshot()
        months, files = _plan(sizes, cap_bytes)
        freed = sum(size for unit, size in sizes.items() if unit.parent.name in months)
        freed += sum(sizes[f] for f in files)
        kept = sorted({unit.parent.name for unit in sizes} - set(months))
        return freed, (kept[0] if kept else None), bool(files)


def _order(picture: Path) -> int:
    """A picture's message id: the order lines were stored in. A leftover ".part" first."""
    return int(picture.stem) if picture.stem.isdigit() else -1


def _plan(sizes: dict[Path, int], cap_bytes: int) -> tuple[list[str], list[Path]]:
    """What goes to get under the cap: whole months, oldest first, but never the newest one;
    then that month's oldest pictures, never its newest (#462)."""
    months: dict[str, list[tuple[Path, int]]] = {}
    for unit, size in sizes.items():
        months.setdefault(unit.parent.name, []).append((unit, size))
    left = sum(sizes.values())
    names = sorted(months)
    gone: list[str] = []
    for name in names[:-1]:
        if left <= cap_bytes:
            break
        gone.append(name)
        left -= sum(size for _, size in months[name])
    files: list[Path] = []
    if names and left > cap_bytes:
        for picture, size in sorted(months[names[-1]], key=lambda f: _order(f[0]))[:-1]:
            if left <= cap_bytes:
                break
            files.append(picture)
            left -= size
    return gone, files

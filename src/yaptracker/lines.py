"""Line pictures (#120): the picture of every stored chat line, so emoji and icons are kept.

data\\lines\\<yyyy-mm>\\<message id>.webp, lossless and in colour, cut from the very frame the
stored reading came from. Lossless WebP rather than PNG: real lines with the game behind them
are ~8 kB instead of ~11 kB (measured, #120). OCR can't spell a heart; the picture still
shows it. Local only, like the database. At most 2 GB by default: the oldest months go first.
"""

import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from yaptracker.capture.source import Region

CAP_BYTES = 2_000_000_000
PAD = 2  # px around the line's box, so outlines and icons at the edge stay whole


def folder_size(folder: Path) -> int:
    if not folder.exists():
        return 0
    return sum(f.stat().st_size for f in folder.rglob("*.webp"))


class LinePictures:
    def __init__(
        self,
        folder: Path,
        enabled: Callable[[], bool] = lambda: True,
        cap_bytes: int = CAP_BYTES,
    ) -> None:
        self._folder, self._enabled, self._cap_bytes = folder, enabled, cap_bytes
        self._lock = threading.Lock()
        self._written = 0  # bytes since the last clean-up check

    def path(self, message_id: int, ts: float) -> Path:
        return self._folder / time.strftime("%Y-%m", time.localtime(ts)) / f"{message_id}.webp"

    def save(self, message_id: int, ts: float, image: np.ndarray, box: Region) -> Path | None:
        """The line's picture; a better reading later saves over it."""
        if not self._enabled():
            return None
        h, w = image.shape[:2]
        x0, y0 = max(0, box.x - PAD), max(0, box.y - PAD)
        x1, y1 = min(w, box.x + box.width + PAD), min(h, box.y + box.height + PAD)
        crop = image[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        target = self.path(message_id, ts)
        target.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(target), crop, [cv2.IMWRITE_WEBP_QUALITY, 101])  # > 100 = lossless
        with self._lock:
            self._written += target.stat().st_size
            check = self._written > 50_000_000  # every ~50 MB, not on every line
            if check:
                self._written = 0
        if check:
            self.clean_up()
        return target

    def clean_up(self) -> None:
        """Oldest months first until under the cap."""
        if not self._folder.exists():
            return
        months = sorted(p for p in self._folder.iterdir() if p.is_dir())
        total = folder_size(self._folder)
        for month in months:
            if total <= self._cap_bytes:
                break
            total -= folder_size(month)
            shutil.rmtree(month)

    def size_bytes(self) -> int:
        return folder_size(self._folder)

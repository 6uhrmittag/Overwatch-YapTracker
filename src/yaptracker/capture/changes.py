"""Skip unchanged frames (#17): OCR only when new chat text appeared.

The closed chat has no background, so the game scene behind it changes every frame. Raw pixel
diffs are useless; instead each frame is reduced to a *text mask*: bright, saturated pixels
right next to a dark outline (Overwatch draws chat text with a dark edge; a bright wall doesn't
have one). A frame counts as changed only if text pixels *appeared*, per line-high band:
- a new message or a scroll adds pixels            -> changed
- lines fading out at match end only lose pixels   -> unchanged
- the scene moving behind the text                 -> unchanged (not in the mask)
"""

from dataclasses import dataclass, field

import cv2
import numpy as np

BANDS = 10  # ~one chat line each for the default box (395 px high at 1440p)


def text_mask(image: np.ndarray) -> np.ndarray:
    """Boolean mask of chat-text pixels in a BGR chat-box image.

    Text = thin bright strokes with a dark outline, in *letter-sized* blobs. Scene edges also
    make thin bright strokes, but as long lines, so blobs that aren't letter-sized are dropped.
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturation, value = hsv[:, :, 1], hsv[:, :, 2]
    # OpenCV ops rather than numpy booleans: the same mask, ~25 % cheaper (#115).
    bright = cv2.bitwise_and(
        cv2.threshold(value, 150, 1, cv2.THRESH_BINARY)[1],
        cv2.threshold(saturation, 70, 1, cv2.THRESH_BINARY)[1],
    )
    wide = cv2.morphologyEx(bright, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    near_dark = cv2.threshold(  # the text outline: dark within 2 px
        cv2.erode(value, np.ones((5, 5), np.uint8)), 89, 1, cv2.THRESH_BINARY_INV
    )[1]
    strokes = cv2.bitwise_and(cv2.subtract(bright, wide), near_dark)

    scale = image.shape[0] / 395  # the default chat box at 1440p is 395 px high
    count, labels, stats, _ = cv2.connectedComponentsWithStats(strokes, connectivity=8)
    w, h, area = (
        stats[:, cv2.CC_STAT_WIDTH],
        stats[:, cv2.CC_STAT_HEIGHT],
        stats[:, cv2.CC_STAT_AREA],
    )
    letter = (h >= 5 * scale) & (h <= 28 * scale) & (w <= 28 * scale) & (area >= 6 * scale**2)
    letter[0] = False  # label 0 is the background
    return letter[labels]


@dataclass
class ChangeDetector:
    """Compares each frame's text mask with the last frame that went to OCR.

    New text must still be there one frame later (0.25 s at 4 fps) before it counts: chat lines
    stand still for seconds, animated scenery and camera moves don't.
    """

    new_share: float = 0.03  # share of a band's text pixels that must be new
    min_pixels: int = 40  # and at least this many, so a few noisy pixels never count
    bands: int = BANDS
    changed: int = 0
    skipped: int = 0
    _reference: np.ndarray | None = field(default=None, repr=False)
    _pending: np.ndarray | None = field(default=None, repr=False)

    def update(self, image: np.ndarray) -> list[tuple[int, int]]:
        """Changed bands as (top, bottom) rows; empty list = unchanged, skip OCR."""
        mask = text_mask(image)
        if self._reference is None or self._reference.shape != mask.shape:
            self._reference, self._pending = np.zeros_like(mask), None
        new = mask & ~_grow(self._reference)  # grown, so 1-2 px jitter isn't "new"
        rows = []
        if self._pending is not None:
            steady = new & _grow(self._pending)  # new last frame too
            edges = np.linspace(0, mask.shape[0], self.bands + 1).astype(int)
            for top, bottom in zip(edges[:-1], edges[1:], strict=True):
                added, present = int(steady[top:bottom].sum()), int(mask[top:bottom].sum())
                if added >= self.min_pixels and added >= self.new_share * present:
                    rows.append((int(top), int(bottom)))
        if rows:
            self._reference, self._pending = mask, None
            self.changed += 1
        else:
            self._reference &= mask  # faded pixels leave the reference too
            self._pending = new if new.sum() >= self.min_pixels else None
            self.skipped += 1
        return rows

    @property
    def skipped_share(self) -> float:
        total = self.changed + self.skipped
        return self.skipped / total if total else 0.0


def _grow(mask: np.ndarray) -> np.ndarray:
    return cv2.dilate(mask.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0

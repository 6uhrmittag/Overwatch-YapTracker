"""Is the top chat row cut off? (#632)

The opened chat shows its history, and the box's edge often cuts the top row in half; a line
that fades out is boxed smaller too. The parser used to know such a row by its text: no
readable start and a weak confidence. A reader trained on chat (#624) reads half a row as
something line-shaped ("[Plckte]: Heyyy" for the lower half of "[Pickle]: Heyyy"),
so the text can't tell any more. The picture can: the letters of a cut row are clearly less
high than those of the rows below it.

Measured on recorded 1440p matches and 4K samples (#632): cut rows come out at 0.4-0.63 of the
other rows' letter height, whole rows mostly near 1. Mostly: a busy background fools the
measure now and then, so it only ever counts together with a weak confidence (parser.parse).
"""

import statistics

import cv2
import numpy as np

from yaptracker.capture.source import Region

MIN_ROWS = 2  # rows below to compare with: a lone line can't be judged, and is never history
SHORT = 0.7  # letters (or the row's box) this much lower than the others: cut
_INK_PIXELS = 3  # bright pixels in a pixel row that make it part of the letters: a "[" is enough
_MARGIN = 3  # px below the box (and above, for the rows below): detection boxes sit tight
# Ink is what is nearly as bright as the row's own brightest letters. Measured on the row
# itself, so a channel in a darker colour isn't "faint" next to brighter rows below, and the
# game picture above a cut row (brighter than the chat's panel, darker than its letters) isn't
# ink. A bright map behind it can only make a row look higher: never cut by mistake.
_AS_BRIGHT = 0.75
_BRIGHTEST = 99  # percentile: the row's letters, not one hot pixel


def _band(image: np.ndarray, box: Region, above: int = _MARGIN) -> np.ndarray:
    top, bottom = max(0, box.y - above), min(image.shape[0], box.y + box.height + _MARGIN)
    return image[top:bottom, max(0, box.x) : max(0, box.x + box.width)].max(axis=2)


def letter_height(image: np.ndarray, box: Region, above: int = _MARGIN) -> int:
    """How many pixel rows the row's letters span: the longest run of pixel rows with ink.
    `above`: how far above the box to look (0 for the top row: above it is the box's edge)."""
    band = _band(image, box, above)
    if band.size == 0:
        return 0
    otsu, _ = cv2.threshold(band, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    threshold = max(otsu, _AS_BRIGHT * float(np.percentile(band, _BRIGHTEST)))
    best = run = 0
    for inked in (band > threshold).sum(axis=1) >= _INK_PIXELS:
        run = run + 1 if inked else 0
        best = max(best, run)
    return best


def clipped(image: np.ndarray, top: Region, below: list[Region]) -> bool:
    """The top row's letters, or its box, are clearly lower than those of the rows below.
    Never raises: a row it can't measure counts as whole (the old rule decides)."""
    heights = [h for h in (letter_height(image, box) for box in below) if h > 0]
    if len(heights) < MIN_ROWS or top.width <= 0:
        return False
    if top.height < SHORT * statistics.median(box.height for box in below):
        return True
    return 0 < letter_height(image, top, above=0) < SHORT * statistics.median(heights)

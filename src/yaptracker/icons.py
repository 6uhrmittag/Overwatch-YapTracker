"""Which icon a "◇" is (#121): Overwatch's own chat icons get their name back.

The icons after a callout ("Thanks!" and its thumb) are white shapes of one size. A small
template of each (data/icons/<name>.png, the white shape only, cut at 2560x1440) is slid over
the line's picture (#120): the whole row, as it's saved, so new lines and stored ones are
named from the same pixels. Only the "whiteness" (the darkest of blue, green, red) is compared:
chat text is coloured, the icons are not. A "◇" becomes "[icon:thumbs-up]" only when exactly as
many icons are found as the text has marks; everything else stays "◇", and the picture stays.
"""

import logging
from functools import cache
from pathlib import Path

import cv2
import numpy as np

from yaptracker import images
from yaptracker.glyphs import GLYPH, tag

log = logging.getLogger(__name__)
FOLDER = Path(__file__).parent / "data" / "icons"
LIBRARY = 1  # one up with every new template: stored lines are then named again, once
# How alike (0-1) a spot must be. On 1026 of Marv's line pictures (2026-11-22, 1440p): 497 of
# 568 real icons scored 0.9+, the best wrong spot of any row 0.78.
ALIKE = 0.85
CONTRAST = 40  # how much whiter than what's around it (0-255): a pattern in a wall isn't one
EDGE = 6  # px
# The templates are 1440p; chat grows with the window: 1080p, 1200p, 1440p, 1600p, 4K.
SCALES = (0.75, 0.83, 1.0, 1.11, 1.5)


@cache
def _templates() -> list[tuple[str, np.ndarray]]:
    """(name, template) at every scale. No folder (a broken install): nothing is named."""
    found = []
    for file in sorted(FOLDER.glob("*.png")):
        image = images.read(file)
        if image is None:
            continue
        shape = image[:, :, 0]
        for scale in SCALES:
            size = (round(shape.shape[1] * scale), round(shape.shape[0] * scale))
            found.append((file.stem, cv2.resize(shape, size, interpolation=cv2.INTER_AREA)))
    if not found:
        log.warning("no icon templates in %s: icons stay ◇", FOLDER)
    return found


def find(picture: np.ndarray) -> list[str]:
    """The names of the known icons in a line's picture, in reading order."""
    # The thumb is taller than the text: its tip is cut off the picture. Rows repeated above
    # and below stand in for it.
    white = cv2.copyMakeBorder(picture.min(axis=2), EDGE, EDGE, 0, 0, cv2.BORDER_REPLICATE)
    spots = []  # (score, x, y, width, height, name)
    for name, template in _templates():
        h, w = template.shape
        if h > white.shape[0] or w > white.shape[1]:
            continue
        scores = cv2.matchTemplate(white, template, cv2.TM_CCOEFF_NORMED)
        while True:  # every spot of this icon, best first
            _, score, _, (x, y) = cv2.minMaxLoc(scores)
            if not score >= ALIKE:  # also NaN: a flat picture
                break
            scores[max(0, y - h) : y + h, max(0, x - w) : x + w] = -1.0
            spot = white[y : y + h, x : x + w]
            shape = template > 127
            if spot[shape].mean() - spot[~shape].mean() >= CONTRAST:
                spots.append((score, x, y, w, h, name))
    kept = []
    for spot in sorted(spots, reverse=True):  # one icon per place: the best reading of it
        _, x, y, w, h, _ = spot
        if all(abs(x - k[1]) >= min(w, k[3]) or abs(y - k[2]) >= min(h, k[4]) for k in kept):
            kept.append(spot)
    # Reading order: a wrapped line's second row comes after its first.
    row = max((k[4] for k in kept), default=1)
    return [k[5] for k in sorted(kept, key=lambda k: ((k[2] + k[4] / 2) // (1.2 * row), k[1]))]


def name(text: str, picture: np.ndarray | None) -> str:
    """The text with its "◇" named, when the picture shows exactly that many known icons."""
    marks = text.count(GLYPH)
    if not marks or picture is None or picture.ndim != 3:
        return text
    names = find(picture)
    if len(names) != marks:
        return text
    for found in names:
        text = text.replace(GLYPH, tag(found), 1)
    return text

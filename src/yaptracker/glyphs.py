"""Emoji and icons in chat become "◇" (#128), never silently dropped.

OCR's boxes stop right before a chat icon (the thumbs-up after "Thanks!", a hero's comms icon,
a heart), so the icon vanished from the text. Here the space after a line's last word and the
gaps between its words are checked for a compact blob that stands out from the background:
- bright and grey, like Overwatch's own chat icons, or
- strongly coloured and solid, like a heart.
Checked by eye on real frames (#128): 38 of 40 marked lines had a real icon; the misses were
scenery behind short lines. The line picture (#120) keeps what the icon really was.
"""

from dataclasses import replace

import cv2
import numpy as np

from yaptracker.ocr.engine import OcrLine

GLYPH = "\u25c7"  # ◇


def _blob(image: np.ndarray, x0: int, x1: int, y0: int, y1: int, height: float) -> bool:
    """A glyph-like blob in image[y0:y1, x0:x1], starting close to its left edge."""
    region = image[max(0, y0) : y1, max(0, x0) : min(image.shape[1], x1)]
    if region.shape[0] < 4 or region.shape[1] < height:
        return False
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV).astype(np.int16)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    mask = ((np.abs(v - np.median(v)) > 40) | (np.abs(s - np.median(s)) > 60)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count < 2:
        return False
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, _, w, h, area = stats[i]
    if not (0.5 * height <= w <= 2.0 * height and h >= 0.5 * height and x <= 0.8 * height):
        return False
    if area < 0.2 * height * height:
        return False
    blob = labels == i
    if not (~blob).any():
        return False
    brighter = v[blob].mean() - np.median(v[~blob])
    icon = brighter > 40 and s[blob].mean() < 90  # Overwatch's white/grey chat icons
    coloured = s[blob].mean() > 150 and area / (w * h) > 0.45  # a solid emoji, e.g. a heart
    return bool(icon or coloured)


def mark(image: np.ndarray, lines: list[OcrLine]) -> list[OcrLine]:
    """Lines with "◇" where an icon sits between words or after the last one."""
    result = []
    for line in lines:
        parts = line.parts or ((line.text, line.box),)
        height = line.box.height
        y0, y1 = line.box.y, line.box.y + height + 1
        pieces = []
        for n, (text, box) in enumerate(parts):
            pieces.append(text.strip())
            end = box.x + box.width
            if n + 1 < len(parts):  # a gap between two words
                if _blob(image, end + 1, parts[n + 1][1].x - 1, y0, y1, height):
                    pieces.append(GLYPH)
            elif _blob(image, end + 1, int(end + 1 + 2.5 * height), y0, y1, height):
                pieces.append(GLYPH)  # right after the last word
        found = GLYPH in pieces
        result.append(replace(line, text=" ".join(pieces)) if found else line)
    return result


def has_glyphs(text: str) -> bool:
    return GLYPH in text

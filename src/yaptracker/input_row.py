"""The chat's input line (#254): while the chat box is open, what you type sits at the bottom in
a light rectangular frame. It's found by that frame, not by OCR'd text, and never stored: a
half-typed, unsent line ("[Mateh] hi: there") must not become a message or a player.
"""

import numpy as np

EDGE_RUN = 0.35  # a frame edge is a light run this share of the box wide; text never is
EDGE_ROWS = 0.025  # an edge is a few rows thin (a bright wall behind the chat is a block)
HEIGHT = (0.06, 0.2)  # the field's height as a share of the chat box's (45 of 395 px at 1440p)
LOW = 0.75  # the field is the box's bottom row (its bottom edge at 97 % in 1440p and 4K samples)
DARK = 90  # the field is dark inside; two edges of a white floor behind closed chat aren't


def _light(image: np.ndarray) -> np.ndarray:
    """Light grey to white, like the frame: bright in every channel, hardly coloured."""
    pixels = image.astype(np.int16)
    low, high = pixels.min(axis=2), pixels.max(axis=2)
    return (low >= 150) & (high - low <= 40)


def _longest_runs(mask: np.ndarray) -> np.ndarray:
    """The longest run of True per row."""
    padded = np.pad(mask.astype(np.int8), ((0, 0), (1, 1)))
    longest = np.zeros(mask.shape[0], int)
    for y, row in enumerate(np.diff(padded, axis=1)):
        starts, ends = np.flatnonzero(row == 1), np.flatnonzero(row == -1)
        if len(starts):
            longest[y] = (ends - starts).max()
    return longest


def input_band(image: np.ndarray) -> tuple[int, int] | None:
    """(top, bottom) rows of the open chat's input field in a chat-box image, or None."""
    height, width = image.shape[:2]
    rows = np.flatnonzero(_longest_runs(_light(image)) >= EDGE_RUN * width)
    if len(rows) < 2:
        return None
    edges, start = [], rows[0]  # runs of neighbouring rows: (first, last)
    for a, b in zip(rows[:-1], rows[1:], strict=True):
        if b - a > 1:
            edges.append((start, a))
            start = b
    edges.append((start, rows[-1]))
    thin = [e for e in edges if e[1] - e[0] + 1 <= max(3, EDGE_ROWS * height)]
    for (top, _), (_, bottom) in zip(thin[:-1], thin[1:], strict=True):
        if not HEIGHT[0] * height <= bottom - top <= HEIGHT[1] * height or bottom < LOW * height:
            continue
        inside = image[top + (bottom - top) // 4 : bottom - (bottom - top) // 4]
        if np.median(inside.min(axis=2)) < DARK:  # typed letters are few: the median is ground
            return int(top), int(bottom)
    return None


def without_input(lines: list, image: np.ndarray) -> list:
    """The OCR lines minus the input row: the field and the [Match] prompt beside it."""
    band = input_band(image)
    if band is None:
        return lines
    top, bottom = band
    margin = (bottom - top) // 4
    return [line for line in lines
            if not top - margin <= line.box.y + line.box.height / 2 <= bottom + margin]  # fmt: skip

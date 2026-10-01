"""Channel from the icon (#173): on HDR screens match and team chat come out the same pale
yellow, but the diamond and the three-person icon still tell them apart. Drawn icons here, so
no real screenshot (and no real name) is in the repo."""

import cv2
import numpy as np

from yaptracker import channels
from yaptracker.capture.source import Region
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import parse

H = 36  # text height of a chat line at 4K
PALE = (150, 230, 255)  # BGR: the washed-out yellow both channels get with HDR on


def frame(rows: list[tuple[str | None, str]]) -> tuple[np.ndarray, list[OcrLine]]:
    """A dark chat box; each row: its icon ("diamond", "team" or None) and its text."""
    image = np.full((60 + len(rows) * 50, 900, 3), 12, np.uint8)
    lines = []
    for i, (icon, text) in enumerate(rows):
        x, y = 100, 30 + i * 50
        cx, cy = int(x - 0.85 * H), y + H // 2
        if icon == "diamond":
            r = int(0.2 * H)
            corners = np.array([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)])
            cv2.fillPoly(image, [corners], PALE)
        elif icon == "team":
            for dx in (-12, 0, 12):  # three people: a head and a body each
                cv2.circle(image, (cx + dx, cy - 6), 3, PALE, -1)
                cv2.ellipse(image, (cx + dx, cy + 5), (4, 5), 0, 0, 360, PALE, -1)
        cv2.rectangle(image, (x, y + 8), (x + 12 * len(text), y + H - 8), PALE, -1)  # "text"
        lines.append(OcrLine(text, 0.99, Region(x, y, 12 * len(text), H)))
    return image, lines


def channels_of(rows) -> list[str]:
    image, ocr = frame(rows)
    return [line.channel for line in channels.assign(parse(ocr), image, {})]


def test_same_colour_but_the_icon_tells_match_from_team():
    assert channels_of([("diamond", "[Pickle]: gg"), ("team", "[Void]: on my way")]) == [
        "match",
        "team",
    ]


def test_no_icon_falls_back_to_the_colour():
    assert channels_of([(None, "[Pickle]: gg")]) == ["unknown"]  # pale yellow matches no colour


def test_a_wrapped_line_keeps_the_icon_of_its_first_row():
    image, _ = frame([("team", "[Void]: this is a long line that"), (None, "wraps onto a second")])
    ocr = [OcrLine("[Void]: this is a long line that", 0.99, Region(100, 30, 400, H)),
           OcrLine("wraps onto a second", 0.99, Region(100, 70, 230, H))]  # fmt: skip
    (line,) = channels.assign(parse(ocr), image, {})
    assert line.channel == "team" and line.text.endswith("wraps onto a second")


def test_clear_icons_teach_the_colours():
    image, ocr = frame([("diamond", "[Pickle]: gg"), ("team", "[Void]: hi")])
    learned = channels.learn(parse(ocr), image)
    assert set(learned) == {"match", "team"}


def test_a_bright_background_hides_the_icon():
    image, ocr = frame([("diamond", "[Pickle]: gg")])
    image[:, :95] = PALE  # the background behind the icon is as bright as the text
    (line,) = parse(ocr)
    assert channels.icon_shape(image, line.head) is None

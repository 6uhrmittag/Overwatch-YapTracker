"""Two chat lines glued into one (#329): the second line's brackets read as I/l, so it looked
like a wrapped continuation. Its own icon now always starts a new line, and the misread
brackets are a line start with a clean name. Names are made up (the repo is public)."""

import time

import cv2
import numpy as np
import pytest

from yaptracker import channels
from yaptracker.capture.source import Region
from yaptracker.identity import Identity
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import parse
from yaptracker.players import PlayerMatcher
from yaptracker.store.repo import Store

H = 36
ORANGE, BLUE = (40, 150, 255), (255, 120, 40)  # BGR


def rows(*shown, gap=40):
    """Rows as close as a wrap (gap < 1.4 x height); each (icon colour or None, text)."""
    image = np.full((60 + len(shown) * gap, 900, 3), 12, np.uint8)
    lines = []
    for i, (icon, text) in enumerate(shown):
        x, y = 100, 20 + i * gap
        cx, cy, r = int(x - 0.85 * H), y + H // 2, int(0.18 * H)
        if icon is not None:
            diamond = np.array([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)])
            cv2.fillPoly(image, [diamond], icon)
        cv2.rectangle(image, (x, y + 8), (x + 12 * len(text), y + H - 8), ORANGE, -1)  # "text"
        lines.append(OcrLine(text, 0.99, Region(x, y, 12 * len(text), H)))
    return image, lines


def parsed(image, lines):
    return [(line.speaker, line.text) for line in
            parse(lines, has_icon=lambda box: channels.has_icon(image, box))]  # fmt: skip


def test_two_icon_rows_are_never_joined_whatever_their_text():
    image, lines = rows((ORANGE, "[Alpha]: yay first play of the game"),
                        (ORANGE, "IBravolnCharliel: sorrv we are in class"))  # fmt: skip
    assert parsed(image, lines) == [("Alpha", "yay first play of the game"),
                                    ("BravolnCharlie", "sorrv we are in class")]  # fmt: skip
    image, lines = rows((ORANGE, "[Alpha]: yay first play of the game"),
                        (ORANGE, "nothing OCR knows as a start"))  # fmt: skip
    assert len(parsed(image, lines)) == 2  # the icon alone is enough


def test_a_real_wrap_without_icon_still_joins_even_on_another_colour_blob():
    image, lines = rows((ORANGE, "[Alpha]: this is a long line that"), (None, "wraps onto two"))
    assert parsed(image, lines) == [("Alpha", "this is a long line that wraps onto two")]
    cv2.rectangle(image, (60, 70), (75, 80), BLUE, -1)  # bright map behind the wrap
    assert parsed(image, lines) == [("Alpha", "this is a long line that wraps onto two")]


@pytest.mark.parametrize("text, name", [
    ("IBravolnCharliel: sorry", "BravolnCharlie"),
    ("1Pickle1: gg", "Pickle"),
    ("lPicklel: gg", "Pickle"),
    ("|Pickle|: gg", "Pickle"),
    ("[Pickle]: gg", "Pickle"),
])  # fmt: skip
def test_misread_brackets_are_a_typed_line_with_the_clean_name(text, name):
    (line,) = parse([OcrLine(text, 0.99, Region(100, 20, 300, H))])
    assert (line.kind, line.speaker) == ("message", name)


def test_text_that_starts_with_i_is_still_text():
    (line,) = parse([OcrLine("Ihr seid: so gut", 0.99, Region(100, 20, 300, H))])
    assert line.kind == "unknown"  # a space in the "name": no start


def test_the_ln_swap_finds_the_known_player(tmp_path):
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        players = PlayerMatcher(store, Identity)
        known = players.link("BravoInCharlie", time.time())
        assert players.link("BravolnCharlie", time.time()) == known
    finally:
        store.close()

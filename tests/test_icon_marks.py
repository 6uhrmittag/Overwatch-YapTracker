"""◇ for chat icons stays put (#259): known icon callouts always have it, and a line keeps it
once a good reading saw it."""

import pytest

from yaptracker.capture.source import Region
from yaptracker.dedup import Dedup
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import parse


def comms(text, confidence=0.98, y=100):
    return OcrLine(f"Pickle (Moira): {text}", confidence, Region(64, y, 400, 24))


@pytest.mark.parametrize("said", ["Group up!", "Group up! ◇", "Thanks!", "Fall back!",
                                  "I need healing!", "Group Up!"])  # fmt: skip
def test_icon_callouts_always_carry_their_mark(said):
    (line,) = parse([comms(said)])
    assert line.text.endswith("◇") and line.text.count("◇") == 1


def test_callouts_without_an_icon_get_none():
    (line,) = parse([comms("Hello!")])
    assert line.text == "Hello!"


def test_a_mark_one_good_reading_saw_stays_when_later_readings_miss_it():
    dedup = Dedup()
    with_icon = parse([OcrLine("[Pickle]: gg ◇", 0.98, Region(64, 100, 400, 24))])
    without = parse([OcrLine("[Pickle]: gg", 0.99, Region(64, 100, 400, 24))])
    (yap,), _ = dedup.update(100.0, with_icon)
    for t in range(1, 4):  # the icon blob fails on three later frames
        dedup.update(100.0 + t, without)
    assert yap.best.text == "gg ◇"


def test_a_weak_reading_with_a_mark_does_not_add_one():
    dedup = Dedup()
    weak = parse([OcrLine("[Pickle]: gg ◇", 0.5, Region(64, 100, 400, 24))])
    good = parse([OcrLine("[Pickle]: gg", 0.99, Region(64, 100, 400, 24))])
    (yap,), _ = dedup.update(100.0, good)
    dedup.update(101.0, weak)
    assert yap.best.text == "gg"

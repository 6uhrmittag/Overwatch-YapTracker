"""A line said again keeps everything around it (#296): before, the repeat was paired with the
stored line, and the rows between them counted as already seen and were lost."""

from yaptracker.capture.source import Region
from yaptracker.dedup import Dedup
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import parse


def read(*texts):
    return parse([OcrLine(t, 0.97, Region(64, 100 + 40 * n, 400, 24)) for n, t in enumerate(texts)])


def test_a_repeat_after_another_line_keeps_both():
    dedup = Dedup()
    dedup.update(100.0, read("[Bo]: schon"))
    new, _ = dedup.update(106.0, read("[Bo]: schon", "[Ana]: ok", "[Bo]: schon"))
    assert [y.best.text for y in new] == ["ok", "schon"]


def test_a_repeat_right_below_is_a_new_line():
    dedup = Dedup()
    dedup.update(100.0, read("[Ana]: hi", "[Bo]: gg"))
    new, _ = dedup.update(103.0, read("[Ana]: hi", "[Bo]: gg", "[Bo]: gg"))
    assert [y.best.text for y in new] == ["gg"]
    again, _ = dedup.update(104.0, read("[Ana]: hi", "[Bo]: gg", "[Bo]: gg"))
    assert again == []  # read again: nothing new


def test_scrolling_still_lines_up():
    dedup = Dedup()
    dedup.update(100.0, read("[Ana]: a", "[Bo]: b", "[Cy]: c"))
    new, _ = dedup.update(102.0, read("[Bo]: b", "[Cy]: c", "[Dee]: d"))
    assert [y.best.text for y in new] == ["d"]

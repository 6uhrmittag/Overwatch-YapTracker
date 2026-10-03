"""Chat reads without the text-detection step (#249): the text mask's rows, recognition only."""

import logging

import numpy as np
import pytest

from tests.test_ocr import demo_chat_crop
from yaptracker import reader as reader_module
from yaptracker.ocr import engine as ocr
from yaptracker.ocr.engine import text_pieces


def similarity(lines: list[str]) -> float:
    from rapidfuzz.distance import Levenshtein

    from yaptracker.demo import _LINES

    truth = [line[1] for line in _LINES]
    return sum(Levenshtein.normalized_similarity(a.lower(), b.lower())
               for a, b in zip(truth, lines, strict=True)) / len(truth)  # fmt: skip


def test_rows_read_at_least_as_well_as_detection_on_the_demo_chat():
    engine = ocr.get("rapidocr")
    crop = demo_chat_crop()
    detected = [line.text for line in engine.read(crop)]
    rows = engine.read_rows(crop, text_scale=1.0)
    assert rows is not None and len(rows) == len(detected)
    assert similarity([line.text for line in rows]) >= similarity(detected)
    assert all(line.parts for line in rows)  # boxes for the icon, ◇ and glued-text steps
    # tight boxes, like detection's: the channel icon (#173) is looked for left of them
    assert [line.box.x for line in rows] == pytest.approx([line.box.x for line in
                                                           engine.read(crop)], abs=3)  # fmt: skip


def test_no_text_no_read_and_odd_rows_fall_back_to_detection():
    assert text_pieces(np.zeros((395, 615, 3), np.uint8), 1.0) == []
    crop = demo_chat_crop()
    tall = np.vstack([crop[:120]] * 1)
    stacked = tall.copy()
    stacked[40:80] = tall[20:60]  # lines pushed into each other: rows can't be told apart
    pieces = text_pieces(stacked, 1.0)
    assert pieces is None or all(h < 1.6 * 25 * 1.3 for _, _, _, h in pieces)


class Clock:
    def __init__(self):
        self.now, self.cpu = 1000.0, 50.0


def test_above_the_cpu_goal_it_reads_every_3_s_for_a_minute(monkeypatch, tmp_path, caplog):
    from yaptracker.matches import MatchTracker
    from yaptracker.pause import Pause
    from yaptracker.store.repo import Store

    clock = Clock()
    monkeypatch.setattr(reader_module.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(reader_module.time, "process_time", lambda: clock.cpu)
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        r = reader_module.ChatReader(lambda image: [], store, MatchTracker(store, Pause()))
        with caplog.at_level(logging.INFO, logger="yaptracker.reader"):
            clock.now += 61
            clock.cpu += 12.2  # 20 % of a core over that minute
            r._count(0.4)
            assert r.busy
            clock.now += 61
            clock.cpu += 3.0  # 5 %
            r._count(0.2)
            assert not r.busy
        assert "reading every 3 s for a minute" in caplog.records[0].getMessage()
    finally:
        store.close()

"""Weak readings get read again while the line is on screen; a good one replaces them (#195)."""

import numpy as np

from yaptracker.capture.source import Region
from yaptracker.dedup import Dedup
from yaptracker.matches import MatchTracker
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import ChatLine
from yaptracker.pause import Pause
from yaptracker.quality import reading_quality
from yaptracker.reader import REREADS, ChatReader
from yaptracker.store.repo import Store

BLACK = np.zeros((395, 615, 3), np.uint8)


def test_the_score_is_confidence_minus_junk():
    assert reading_quality("lemon ur a goid boy", 0.98) == 0.98
    assert reading_quality("Schöne Grüße, Spaß ◇", 0.97) == 0.97  # German and the icon mark
    assert reading_quality("lemon ur a goid boy 型 2325", 0.98) < 0.95  # a sign behind the box
    assert reading_quality("", 0.99) == 0.0


def yap(text, confidence):
    return ChatLine("message", "match", text, confidence, Region(0, 0, 100, 20), speaker="Pickle")


def test_a_good_reading_wins_and_stays():
    dedup = Dedup()
    (line,), _ = dedup.update(0.0, [yap("wawe awaw", 0.62)])
    assert line.weak
    _, improved = dedup.update(1.5, [yap("waweawaw", 0.99)])
    assert improved and line.best.text == "waweawaw" and not line.weak
    dedup.update(3.0, [yap("wawe awaw", 0.62)])
    dedup.update(4.5, [yap("wawe awaw", 0.62)])  # read badly twice more: the good one stays
    assert line.best.text == "waweawaw"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_the_reader_asks_for_a_few_more_reads_and_stores_the_better_one(tmp_path):
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        frames = [BLACK.copy() for _ in range(REREADS + 1)]
        bad = [OcrLine("[Pickle]: hey guvs", 0.66, Region(64, 300, 300, 24))]
        good = [OcrLine("[Pickle]: hey guys", 0.99, Region(64, 300, 300, 24))]
        reads = {id(frames[0]): bad, id(frames[1]): bad, id(frames[2]): good}
        reads.update({id(f): good for f in frames[3:]})
        clock = Clock()
        tracker = MatchTracker(store, Pause(), clock=clock)
        tracker.capture_alive(clock.now)
        reader = ChatReader(lambda image: reads[id(image)], store, tracker, clock=clock)
        reader.read_frame(clock.now, frames[0])
        assert reader.wants_reread()  # weak, and nothing new will come from the change detector
        clock.now += 1.5
        reader.read_frame(clock.now, frames[1])
        assert reader.wants_reread()
        clock.now += 1.5
        reader.read_frame(clock.now, frames[2])
        (stored,) = store.messages(tracker.match_id)
        assert stored.text == "hey guys"  # the better reading replaced it
        assert not reader.wants_reread()  # and no more reads needed
    finally:
        store.close()


def test_re_reads_stop_after_a_few_or_when_the_line_is_gone(tmp_path):
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        frames = [BLACK.copy() for _ in range(REREADS + 2)]
        bad = [OcrLine("[Pickle]: Hy DNY", 0.66, Region(64, 300, 300, 24))]
        reads = {id(f): bad for f in frames}
        clock = Clock()
        tracker = MatchTracker(store, Pause(), clock=clock)
        tracker.capture_alive(clock.now)
        reader = ChatReader(lambda image: reads[id(image)], store, tracker, clock=clock)
        reader.read_frame(clock.now, frames[0])
        for frame in frames[1 : REREADS + 1]:
            assert reader.wants_reread()
            clock.now += 1.5
            reader.read_frame(clock.now, frame)
        assert not reader.wants_reread()  # used up: it stays as read
        assert len(store.messages(tracker.match_id)) == 1
    finally:
        store.close()

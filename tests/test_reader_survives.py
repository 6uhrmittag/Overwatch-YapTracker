"""The chat reader never dies silently (#457): a failing read, then a failing store on the
error path, and the next frame is still read; reads failing in a row become a gap and a word."""

import sqlite3
import time

import numpy as np
import pytest

from yaptracker import side_work
from yaptracker.capture.source import Region
from yaptracker.matches import MatchTracker
from yaptracker.ocr.engine import OcrLine
from yaptracker.pause import Pause
from yaptracker.reader import FAIL_LIMIT, ChatReader
from yaptracker.store.repo import Store

FRAME = np.zeros((395, 615, 3), np.uint8)
LINE = [OcrLine("[Pickle]: wahoo team", 0.99, Region(64, 300, 300, 24))]


@pytest.fixture
def store(tmp_path):
    side_work.reset()
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def test_a_failing_store_on_the_error_path_leaves_the_reader_alive(store, monkeypatch):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(time.time())
    reads = iter([RuntimeError("OCR fell over")])

    def read(image):
        failure = next(reads, None)
        if failure is not None:
            raise failure
        return LINE

    def locked(ts):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(tracker, "chat_changed", locked)  # used to end the thread (#457)
    reader = ChatReader(read, store, tracker, min_gap_s=0.0)
    reader.start()
    try:
        reader.offer(FRAME)
        end = time.monotonic() + 3
        while reader.failing == 0 and time.monotonic() < end:
            time.sleep(0.01)
        monkeypatch.undo()
        reader.offer(FRAME)  # the next frame
        while not store.messages(tracker.match_id) and time.monotonic() < end:
            time.sleep(0.01)
        assert reader._thread.is_alive() and [m.text for m in store.messages(tracker.match_id)]
    finally:
        reader.stop()


def test_reads_failing_in_a_row_open_a_gap_and_a_good_read_closes_it(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(1000.0)
    ok = {"now": False}

    def read(image):
        if not ok["now"]:
            raise RuntimeError("model file missing")
        return LINE

    reader = ChatReader(read, store, tracker)
    for n in range(FAIL_LIMIT):
        try:
            reader.read_frame(1000.0 + n, FRAME)
        except RuntimeError:
            reader._failed_read(1000.0 + n)  # what the thread does
    assert reader.failing == FAIL_LIMIT and store.all_gaps() == [(1004.0, None, "crash")]
    ok["now"] = True
    reader.read_frame(1010.0, FRAME)
    reader._read_ok(1010.0)
    assert reader.failing == 0 and store.all_gaps() == [(1004.0, 1010.0, "crash")]

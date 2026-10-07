"""Quitting with "after the match" frames unread keeps them for the next start (#349)."""

import numpy as np
import pytest

from yaptracker.capture.source import Region
from yaptracker.later import KEEP_S, LaterFrames
from yaptracker.matches import MatchTracker
from yaptracker.ocr.engine import OcrLine
from yaptracker.pause import Pause
from yaptracker.reader import ChatReader
from yaptracker.store.repo import Store

T0 = 1_000_000.0


@pytest.fixture
def db(tmp_path):
    return tmp_path / "yaptracker.db", tmp_path / "backups"


def image(shade):
    return np.full((40, 400, 3), shade, np.uint8)


def read(img):  # the fake OCR knows each frame by its shade
    lines = {10: ["[Pip]: gl hf"], 20: ["[Pip]: gl hf", "[Pip]: gg wp"]}[int(img[0, 0, 0])]
    return [OcrLine(text, 0.99, Region(64, 4 + 30 * n, 300, 24)) for n, text in enumerate(lines)]


def reader_for(store, tracker, unread, clock, **kwargs):
    later = LaterFrames(lambda: 0.0, unread.parent / "note.json", unread=unread)
    return ChatReader(read, store, tracker, clock=lambda: clock[0], later=later,
                      read_kept=lambda img, mode: read(img), **kwargs)  # fmt: skip


def test_a_quit_keeps_them_and_the_next_start_reads_them_into_their_match(db, tmp_path):
    unread = tmp_path / "unread"
    store = Store.open(*db)
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    tracker.new_match(T0, "heroselect", "COMPETITIVE", "Busan")
    match, clock = tracker.match_id, [T0 + 5]
    reader = reader_for(store, tracker, unread, clock, deferring=lambda: True)
    reader.start()
    reader.offer(image(10), "after")
    clock[0] = T0 + 9
    reader.offer(image(20), "after")
    assert not unread.exists()  # nothing written to disk during the match
    reader.stop()
    tracker.stop()
    assert (unread / "index.json").exists() and store.all_gaps() == []  # kept, not lost
    store.close()

    store = Store.open(*db)  # the next start
    tracker = MatchTracker(store, Pause())
    later = reader_for(store, tracker, unread, [T0 + 600]).later
    assert later.restore(now=T0 + 600) is None and len(later) == 2
    assert not unread.exists()  # read into memory, the folder is gone
    again = ChatReader(read, store, tracker, later=later, read_kept=lambda img, mode: read(img))
    while (kept := later.pop()) is not None:
        again.read_frame(kept.ts, kept.image, kept)
    assert [(m.ts, m.text) for m in store.messages(match)] == [(T0 + 5, "gl hf"),
                                                              (T0 + 9, "gg wp")]  # fmt: skip
    assert store.all_gaps() == []
    store.close()


def test_frames_older_than_two_days_become_a_gap(db, tmp_path):
    unread = tmp_path / "unread"
    later = LaterFrames(lambda: 0.0, None, unread=unread)
    later.add(T0, image(10), 1, "after")
    later.add(T0 + 30, image(20), 1, "after")
    assert later.close() is None
    fresh = LaterFrames(lambda: 0.0, None, unread=unread)
    assert fresh.restore(now=T0 + 30 + KEEP_S + 1) == (T0, T0 + 30)  # for the gap record
    assert len(fresh) == 0 and not unread.exists()


def test_a_half_written_folder_is_dropped_quietly(tmp_path):
    unread = tmp_path / "unread"
    unread.mkdir()
    np.save(unread / "0000.npy", image(10))  # cut off before index.json
    later = LaterFrames(lambda: 0.0, None, unread=unread)
    assert later.restore(now=T0) is None and len(later) == 0 and not unread.exists()


def test_a_disk_that_says_no_still_leaves_a_gap(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("not a folder")
    later = LaterFrames(lambda: 0.0, None, unread=blocked / "unread")
    later.add(T0, image(10), 1, "after")
    assert later.close() == (T0, T0)


def test_the_reader_keeps_the_buffer_it_was_given_even_when_empty(db):
    """An empty buffer is falsy: the app's one (with its crash note) was swapped (#349)."""
    store = Store.open(*db)
    try:
        later = LaterFrames(lambda: 0.0, None)
        assert ChatReader(read, store, MatchTracker(store, Pause()), later=later).later is later
    finally:
        store.close()

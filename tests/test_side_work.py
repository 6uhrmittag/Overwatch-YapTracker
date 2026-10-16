"""Side work never fails a chat read (#452): line pictures, debug samples, a full disk, and
Windows OCR saying "Operation aborted"."""

import logging

import numpy as np
import pytest

from yaptracker import reading_mode as modes
from yaptracker import side_work
from yaptracker.capture.source import Region
from yaptracker.debug import LOW_DISK_BYTES, DebugSamples
from yaptracker.matches import MatchTracker
from yaptracker.ocr.engine import OcrLine
from yaptracker.pause import Pause
from yaptracker.reader import ChatReader
from yaptracker.store.repo import Store

FRAME = np.zeros((395, 615, 3), np.uint8)
LINE = [OcrLine("[Pickle]: wahoo team", 0.99, Region(64, 300, 300, 24))]
FULL = OSError(28, "No space left on device")


@pytest.fixture(autouse=True)
def _fresh_notes():
    side_work.reset()


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class FullDisk:
    def save(self, *args):
        raise FULL


def reader(store, **side):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(1000.0)
    return ChatReader(lambda image: LINE, store, tracker, **side), tracker


def full(*read):
    raise FULL


def test_a_picture_or_debug_write_on_a_full_disk_still_stores_the_line(store, caplog):
    chat, tracker = reader(store, pictures=FullDisk(), on_read=full)
    with caplog.at_level(logging.WARNING, logger="yaptracker.side_work"):
        new = chat.read_frame(1000.0, FRAME)
        chat.read_frame(1001.0, FRAME)
    assert len(new) == 1 and [m.text for m in store.messages(tracker.match_id)] == ["wahoo team"]
    assert caplog.text.count("saving a line picture failed, the chat line is kept") == 1
    assert caplog.text.count("saving a debug sample failed") == 1  # once a minute per kind


def test_the_note_comes_again_after_a_minute_with_the_count(caplog):
    clock = Clock()
    with caplog.at_level(logging.WARNING, logger="yaptracker.side_work"):
        for _ in range(3):
            side_work.failed("saving a line picture", FULL, clock)
        clock.now += 60
        side_work.failed("saving a line picture", FULL, clock)
    assert (
        caplog.text.count("the chat line is kept") == 2
        and "(2 more since the last note)" in caplog.text
    )


class Engine:
    def __init__(self, aborts=0):
        self.calls, self.aborts = 0, aborts

    def read(self, image, scale):
        self.calls += 1
        if self.calls <= self.aborts:
            raise OSError(-2147467260, "Operation aborted")  # E_ABORT from Windows OCR
        return LINE


@pytest.mark.parametrize(("aborts", "windows", "best"), [(1, 2, 0), (2, 2, 1)])
def test_windows_ocr_aborted_is_tried_once_more_then_read_with_best(store, aborts, windows, best):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(1000.0)
    tracker.new_match(1010.0, source="heroselect", mode="QUICK PLAY", map_name="Busan")
    engines = {"windows": Engine(aborts), "rapidocr": Engine()}
    reading = modes.ReadingMode(lambda: tracker, lambda: "best", lambda: "light",
                                lambda: "rapidocr", get=engines.__getitem__,
                                available=lambda: ["rapidocr", "windows"])  # fmt: skip
    assert reading.read(FRAME, 2.0) == LINE  # no lost frame
    assert (engines["windows"].calls, engines["rapidocr"].calls) == (windows, best)


def test_a_full_disk_pauses_debug_samples_says_so_and_resumes(tmp_path, caplog):
    clock, free = Clock(), [LOW_DISK_BYTES - 1]
    samples = DebugSamples(tmp_path / "debug", lambda: True, clock, free=lambda _: free[0])
    signals = {"end_banner": np.full((25, 82, 3), 200, np.uint8)}
    with caplog.at_level(logging.INFO, logger="yaptracker.debug"):
        samples.on_signals(signals)
        assert samples.disk_low and samples.match_event("end") is None
        clock.now += 30
        free[0] = 2 * LOW_DISK_BYTES
        samples.on_signals(signals)
        assert samples.disk_low  # checked once a minute
        clock.now += 30
        samples.on_signals(signals)
        assert not samples.disk_low and samples.match_event("end") is not None
    assert "Disk almost full: debug samples paused" in caplog.text
    assert "debug samples back on" in caplog.text


def test_a_sample_that_cant_be_written_doesnt_stop_the_capture(tmp_path):
    (tmp_path / "debug").write_text("a file where the folder should be")  # mkdir fails
    samples = DebugSamples(tmp_path / "debug", lambda: True, free=lambda _: 2 * LOW_DISK_BYTES)
    samples.on_signals({"end_banner": np.full((25, 82, 3), 200, np.uint8)})
    assert samples.match_event("end") is None  # no exception into the capture thread

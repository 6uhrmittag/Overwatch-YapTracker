"""Another window over the chat box, read from the screen, isn't chat (#497): "gj E:\\data\\shots"
came from File Explorer on top of Void's game."""

import logging
import time

import numpy as np

from yaptracker.capture.cover import TopWindow, first_cover
from yaptracker.capture.health import CaptureHealth
from yaptracker.capture.source import Frame, Region
from yaptracker.capture.watcher import COVER_GAP_S, CaptureWatcher
from yaptracker.channels import cut_glued
from yaptracker.ocr.engine import OcrLine
from yaptracker.store.repo import Store

BOX = Region(55, 510, 615, 395)  # the chat box on the screen


def test_only_a_visible_window_on_the_box_covers_it():
    explorer = TopWindow((300, 700, 1200, 1100))  # File Explorer over part of the box
    assert first_cover([explorer], BOX) == explorer
    beside = TopWindow((2560, 0, 3840, 1440))  # YapTracker on the second screen
    see_through = [
        TopWindow((0, 0, 2560, 1440), click_through=True),  # Discord's overlay
        TopWindow((0, 0, 2560, 1440), invisible=True),  # layered, alpha 0
        TopWindow((0, 0, 2560, 1440), overlay=True),
    ]  # layered, the whole game
    hidden = [TopWindow((0, 0, 2560, 1440), visible=False),
              TopWindow((0, 0, 2560, 1440), minimised=True),
              TopWindow((0, 0, 2560, 1440), cloaked=True)]  # fmt: skip
    assert first_cover([beside, *see_through, *hidden], BOX) is None
    assert first_cover(iter([beside, *see_through, explorer]), BOX) == explorer
    touching = TopWindow((BOX.x + BOX.width, 0, 2560, 1440))  # right next to it
    assert first_cover([touching], BOX) is None


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Covered:
    """Frames read from the screen: free, then covered for a while, then free again."""

    def __init__(self, clock, pattern):
        self.clock, self.pattern = clock, pattern

    def frames(self):
        for n, cover in enumerate(self.pattern):
            self.clock.now = n * 0.5
            yield Frame(n * 0.5, np.zeros((4, 4, 3), np.uint8), covered=cover)

    def close(self):
        pass


def test_a_covered_frame_is_not_read_said_once_and_a_long_cover_is_a_gap(tmp_path, caplog):
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    clock, read = Clock(), []
    health = CaptureHealth(store, clock=lambda: 1000 + clock.now)
    long = int(COVER_GAP_S / 0.5) + 4  # frames at 2 a second, longer than COVER_GAP_S
    pattern = [None, *["data - File Explorer"] * long, None, None]
    windows = iter([1, None])
    watcher = CaptureWatcher(lambda: next(windows, None), lambda _: Covered(clock, pattern),
                             read.append, health=health, poll_s=0.01, clock=clock)  # fmt: skip
    with caplog.at_level(logging.INFO, logger="yaptracker.capture.watcher"):
        watcher.start()
        end = time.monotonic() + 5
        while watcher.state != "waiting" or len(read) < 3:  # played, and back to waiting
            assert time.monotonic() < end, "timed out"
            time.sleep(0.01)
        watcher.stop()
    store_gaps = store.all_gaps()
    store.close()
    assert [f.covered for f in read] == [None, None, None]  # only the free frames were read
    assert caplog.text.count("chat box covered by another window - not reading") == 1
    assert "File Explorer" not in caplog.text  # titles can be private: Live only
    assert caplog.text.count("chat box free again") == 1
    assert len(store_gaps) == 1 and store_gaps[0][2] == "no_frames"  # longer than COVER_GAP_S
    assert store_gaps[0][1] is not None  # closed once the box was free
    assert watcher.covered is None


def test_a_cover_is_forgotten_when_the_capture_ends(tmp_path):
    clock, read = Clock(), []
    windows = iter([1, None])
    watcher = CaptureWatcher(lambda: next(windows, None),
                             lambda _: Covered(clock, [None, "data - File Explorer"]),
                             read.append, poll_s=0.01, clock=clock)  # fmt: skip
    watcher.start()
    end = time.monotonic() + 5
    while watcher.state != "waiting" or not read:
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)
    watcher.stop()
    assert watcher.covered is None  # Live doesn't keep saying a window is in the way


def line(*words):
    """An OCR line from (text, x, width) words, 20 px high."""
    parts = tuple((text, Region(x, 300, width, 20)) for text, x, width in words)
    return OcrLine(" ".join(t for t, *_ in words), 0.99, Region(words[0][1], 300, 400, 20), parts)


def test_text_far_after_the_message_in_another_colour_is_cut():
    hues = {64: 200.0, 160: 200.0, 400: None}  # the name and "gj" in team blue, the path white
    found = cut_glued([line(("[Pickle]:", 64, 90), ("gj", 160, 20), ("E:\\data\\shots", 400, 120))],
                      np.zeros((395, 615, 3), np.uint8), {"team": 200.0},
                      hue=lambda image, box: hues[box.x])  # fmt: skip
    assert [ln.text for ln in found] == ["[Pickle]: gj"]
    near = cut_glued([line(("[Pickle]:", 64, 90), ("gj", 160, 20), ("wp", 190, 30))],
                     np.zeros((395, 615, 3), np.uint8), {"team": 200.0},
                     hue=lambda image, box: 200.0)  # fmt: skip
    assert [ln.text for ln in near] == ["[Pickle]: gj wp"]  # the message itself stays
    report = cut_glued([line(("[Pickle]:", 64, 90), ("ez", 160, 20), ("[Report]", 400, 70))],
                       np.zeros((395, 615, 3), np.uint8), {"team": 200.0},
                       hue=lambda image, box: 200.0 if box.x < 400 else None)  # fmt: skip
    assert [ln.text for ln in report] == ["[Pickle]: ez [Report]"]  # Overwatch's own link
    unknown = cut_glued([line(("[Pickle]:", 64, 90), ("gj", 160, 20), ("far", 400, 40))],
                        np.zeros((395, 615, 3), np.uint8), {},
                        hue=lambda image, box: None)  # fmt: skip
    assert [ln.text for ln in unknown] == ["[Pickle]: gj far"]  # no colour known: nothing goes

"""Reading per kind of match (#331): light or best by the queue hero select read, best between."""

import json
import logging

import numpy as np
import pytest

from yaptracker import config, paths
from yaptracker import reading_mode as modes
from yaptracker.matches import MatchTracker
from yaptracker.ocr.engine import OcrUnavailable
from yaptracker.pause import Pause
from yaptracker.reader import ChatReader
from yaptracker.store.repo import Store

IMAGE = np.zeros((20, 40, 3), np.uint8)


class FakeEngine:
    def __init__(self, name):
        self.name, self.calls = name, 0

    def read(self, image, scale):
        self.calls += 1
        return []


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


@pytest.fixture
def engines():
    return {"rapidocr": FakeEngine("rapidocr"), "windows": FakeEngine("windows")}


def reading_for(tracker, engines, competitive="light", other="best", available=None):
    return modes.ReadingMode(
        lambda: tracker,
        lambda: competitive,
        lambda: other,
        lambda: "rapidocr",
        get=engines.__getitem__,
        available=lambda: available or ["rapidocr", "windows"],
    )


def test_the_engine_switches_at_hero_select_by_queue_and_back_to_best_after(store, engines):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(1000.0)
    reading = reading_for(tracker, engines)
    assert reading.now() == "best"  # before the first match: the game is idle
    tracker.new_match(1010.0, source="heroselect", mode="COMPETITIVE", map_name="Busan")
    reading.read(IMAGE, 2.0)
    assert (reading.now(), engines["windows"].calls) == ("light", 1)
    tracker.end_match(1600.0, outcome="victory")
    reading.read(IMAGE, 2.0)  # the end screen and post-match chat: idle again
    assert (reading.now(), engines["rapidocr"].calls) == ("best", 1)
    tracker.new_match(1700.0, source="heroselect", mode="GEWERTET", map_name="Busan")
    assert reading.now() == "light"  # the German client
    tracker.new_match(2400.0, source="heroselect", mode="QUICK PLAY", map_name="Busan")
    assert reading.now() == "best"
    assert reading.take_counts() == "light 1, best 1"
    assert reading.take_counts() == ""  # counted per log minute


def test_other_matches_have_their_own_choice_and_a_missed_hero_select_counts_as_other(
    store, engines
):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(1000.0)
    reading = reading_for(tracker, engines, competitive="best", other="light")
    tracker.chat_changed(1010.0)  # a match the chat started: no queue known
    assert reading.now() == "light"
    tracker.new_match(1020.0, source="heroselect", mode="COMPETITIVE", map_name="Busan")
    assert reading.now() == "best"


def test_frames_kept_for_after_the_match_are_read_with_the_best_quality(store, engines, caplog):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(1000.0)
    reading = reading_for(tracker, engines, competitive="after")
    with caplog.at_level(logging.INFO, logger="yaptracker.reading_mode"):
        reading.now()
        tracker.new_match(1010.0, source="heroselect", mode="COMPETITIVE", map_name="Busan")
        assert reading.now() == "after"
    assert "reading: after (Competitive, match" in caplog.text  # for Void's FPS check (#335)
    reading.read(IMAGE, 2.0, "after")
    assert engines["rapidocr"].calls == 1 and reading.take_counts() == "after 1"


def test_light_falls_back_to_best_where_windows_ocr_cannot_run(store, engines, caplog):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(1000.0)
    tracker.new_match(1010.0, source="heroselect", mode="COMPETITIVE", map_name="Busan")
    reading = reading_for(tracker, engines, available=["rapidocr"])
    with caplog.at_level(logging.WARNING, logger="yaptracker.reading_mode"):
        reading.read(IMAGE, 2.0)
    assert engines["rapidocr"].calls == 1 and reading.take_counts() == "best 1"
    assert reading.light_problem == "Windows OCR only runs on Windows"
    assert "reading with the best quality" in caplog.text

    def no_language(name):
        if name == "windows":
            raise OcrUnavailable("Windows has no OCR language installed")
        return engines[name]

    reading = reading_for(tracker, engines)
    reading._get = no_language
    assert reading.engine("light")[0] == "best"
    assert reading.light_problem == "Windows has no OCR language installed"


def test_the_log_line_says_which_mode_read(store, engines, caplog, monkeypatch):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(1000.0)
    tracker.new_match(1010.0, source="heroselect", mode="COMPETITIVE", map_name="Busan")
    reading = reading_for(tracker, engines)
    reader = ChatReader(lambda image: reading.read(image, 2.0), store, tracker,
                        modes=reading.take_counts)  # fmt: skip
    reader._load_since -= 61  # a minute has passed
    with caplog.at_level(logging.INFO, logger="yaptracker.reader"):
        reader.read_frame(1020.0, IMAGE)
    assert "chat reading: 1 frames" in caplog.text and "(light 1)" in caplog.text


def test_defaults_and_choices_persist():
    assert (config.reading("competitive"), config.reading("other")) == ("light", "best")
    config.save_reading("other", "light")
    config.save_reading("competitive", "nonsense")  # hand-edited: back to the default
    assert (config.reading("competitive"), config.reading("other")) == ("light", "light")


def test_windows_ocr_picked_by_hand_carries_over_to_every_match():
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text(json.dumps({"ocr_engine": "windows"}), encoding="utf-8")
    assert config.reading("other") == "light"  # Void's stopgap (#330): still light everywhere
    assert config.reading("competitive") == "light"
    assert config.ocr_engine() == "rapidocr"  # best quality is RapidOCR again
    config.save_reading("other", "best")
    assert config.reading("other") == "best"  # carried over once, not every time

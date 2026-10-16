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


def test_other_matches_have_their_own_choice(store, engines):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(1000.0)
    reading = reading_for(tracker, engines, competitive="best", other="light")
    tracker.new_match(1010.0, source="heroselect", mode="QUICK PLAY", map_name="Busan")
    assert reading.now() == "light"
    tracker.new_match(1600.0, source="heroselect", mode="COMPETITIVE", map_name="Busan")
    assert reading.now() == "best"


@pytest.mark.parametrize("competitive, other, expected", [
    ("after", "best", "after"), ("light", "best", "light"), ("best", "light", "light"),
    ("best", "after", "after"), ("best", "best", "best"),
])  # fmt: skip
def test_an_unknown_queue_reads_the_lighter_of_the_two_choices(
    store, engines, caplog, competitive, other, expected
):
    """Washed-out hero select, or none seen (YapTracker started mid-match): Marv, #345."""
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(1000.0)
    tracker.chat_changed(1010.0)  # a match the chat started: no queue known
    reading = reading_for(tracker, engines, competitive=competitive, other=other)
    with caplog.at_level(logging.INFO, logger="yaptracker.reading_mode"):
        assert reading.now() == expected
    assert f"queue unknown \u2192 treated as {expected}" in caplog.text
    tracker.learn_info("UNRANKED", None)  # not a hero-select start: stays unknown
    assert reading.now() == expected


def test_a_chat_started_match_read_afterwards_still_counts_its_chat(store):
    """#307 drops a chat-started match whose chat lasted under 3 min; read afterwards, the
    chat box changing still counts (#345)."""
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(1000.0)
    tracker.chat_changed(1010.0)
    first = tracker.match_id
    reader = ChatReader(lambda image: [], store, tracker, clock=lambda: 1400.0)
    reader.offer(np.zeros((4, 4, 3), np.uint8), "after")  # 6.5 min in, not read yet
    tracker.new_match(1500.0, source="heroselect", mode="UNRANKED", map_name="Busan")
    assert tracker.previous_match_id == first  # a real match, not chat outside one


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
    assert reading.read_in(0) == "best"  # quiet chat, light can't run: best (#444)
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
    """Fresh: Competitive after the match, other matches live and light (#413)."""
    assert (config.reading("competitive"), config.reading("other")) == ("after", "light")
    config.save_reading("other", "best")
    config.save_reading("competitive", "nonsense")  # hand-edited: back to the default
    assert (config.reading("competitive"), config.reading("other")) == ("after", "best")


def test_a_saved_reading_choice_keeps_best_for_other_matches():
    """#413: Marv set Competitive to best when other matches defaulted to best; his other
    matches stay best. Someone choosing only after the new default gets light there."""
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text(json.dumps({"reading": {"competitive": "best"}}))
    assert (config.reading("competitive"), config.reading("other")) == ("best", "best")
    paths.config_file().write_text("{}")  # a new install
    config.forget()
    config.save_reading("competitive", "best")
    assert config.reading("other") == "light"


def test_windows_ocr_picked_by_hand_carries_over_to_every_match():
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text(json.dumps({"ocr_engine": "windows"}), encoding="utf-8")
    assert config.reading("other") == "light"  # Void's stopgap (#330): still light there
    assert config.reading("competitive") == "after"  # ranked: after the match (#336)
    assert config.ocr_engine() == "rapidocr"  # best quality is RapidOCR again
    config.save_reading("other", "best")
    assert config.reading("other") == "best"  # carried over once, not every time


def test_the_fps_line_names_what_really_read_in_the_match(store, engines, caplog):
    """#444, the real reader and meter together: best reads between matches (a tidy-up) don't
    leak into the match; frames kept from before, read now with best, outvote a light read;
    quiet chat names the mode for now."""
    from tests.test_game_fps import strip, top_right
    from yaptracker.game_fps import FpsMeter

    clock, values = Clock(), iter(range(100, 200))
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(1000.0)
    reading = reading_for(tracker, engines, other="light")
    reading._clock = clock
    for _ in range(50):
        reading.read(IMAGE, 2.0, "after")  # between matches: best
        clock.now += 0.1
    state = {"now": "running, between matches"}
    meter = FpsMeter(lambda box: f"FPS:{next(values)}", lambda: state["now"], clock,
                     mode=lambda now, since: reading.read_in(since) if now.endswith("in match")
                     else None)  # fmt: skip
    signals = {"fps": strip(top_right(1440, 150), 1440)}
    with caplog.at_level(logging.INFO, logger="yaptracker.game_fps"):
        for t in range(130):
            if t == 10:
                tracker.new_match(1010.0, source="heroselect", mode="UNRANKED", map_name="Busan")
                state["now"] = "running, in match"
            if t == 70:
                kept_at = clock.now
                for _ in range(3):  # kept frames from before, read now: the best engine
                    reading.read(IMAGE, 2.0, "after")
            if t in (71, 72):
                reading.read(IMAGE, 2.0)  # live, light
            meter.update(signals, 1440)
            clock.now += 1
        clock.now += 60
        meter.update(signals, 1440)  # closes the last minute
    lines = [r.getMessage().split(" — ")[1].split(";")[0] for r in caplog.records
             if r.name == "yaptracker.game_fps"]  # fmt: skip
    assert lines[1:] == ["running, in match, light", "running, in match, light"]
    assert reading.read_in(kept_at) == "best"  # 3 best vs 2 light: one sample, outvoted


def test_read_in_counts_only_the_window_and_changes_nothing(store, engines):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(1000.0)
    tracker.new_match(1010.0, source="heroselect", mode="UNRANKED", map_name="Busan")
    clock = Clock()
    reading = reading_for(tracker, engines, other="light")
    reading._clock = clock
    for _ in range(3):
        reading.read(IMAGE, 2.0, "after")  # kept frames: the best engine
    clock.now += 10
    reading.read(IMAGE, 2.0)  # a live light read
    assert reading.read_in(0) == "best" and reading.read_in(0) == "best"  # asked twice: same
    assert reading.read_in(clock.now - 1) == "light"
    assert reading.read_in(clock.now + 1) == "light"  # quiet: the mode for now


class Clock:
    def __init__(self):
        self.now = 5000.0

    def __call__(self):
        return self.now

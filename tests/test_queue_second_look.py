"""The queue at hero select decides how chat is read (#331). Missed at the first look, it gets
more looks while hero select is up, also with colour tricks against glare (#342)."""

import numpy as np
import pytest

from yaptracker import reading_mode, signals
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.signals import IN_MATCH_EVERY_S, INFO_TRIES, HeroSelect, read_info
from yaptracker.store.repo import Store

BANNER = np.full((60, 780, 3), 200, np.uint8)


@pytest.fixture(autouse=True)
def bright(monkeypatch):
    monkeypatch.setattr(signals, "has_bright_text", lambda image, *a, **k: True)  # a banner


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def glare():
    """A yellow-white corner: a colour image, so the variants are grey ones."""
    image = np.zeros((240, 780, 3), np.uint8)
    image[:] = (120, 240, 250)
    return image


def grey(image):
    return np.array_equal(image[:, :, 0], image[:, :, 1])


def test_a_colour_trick_finds_the_queue_the_plain_read_missed():
    reads = []

    def read_lines(image):
        reads.append("grey" if grey(image) else "colour")
        return ["COMPETITIVE ATTACK", "BUSAN"] if grey(image) else ["TACK", "BUSAN"]

    assert read_info(read_lines, glare()) == ("COMPETITIVE", "Busan")
    assert reads == ["colour", "grey"]  # stops at the first look that has it
    reads.clear()
    assert read_info(lambda image: reads.append(1) or ["UNRANKED ATTACK", "BUSAN"],
                     glare()) == ("UNRANKED", "Busan")  # fmt: skip
    assert reads == [1]  # read at once: no extra looks


def test_later_looks_give_the_running_match_its_queue_and_its_reading_mode(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(1000.0)
    clock = [0.0]
    first, later = glare(), glare()
    infos = {id(first): ["TACK", "BUSAN"], id(later): ["COMPETITIVE ATTACK", "BUSAN"]}
    hs = HeroSelect(
        lambda image: "ASSEMBLE YOUR TEAM",
        lambda image: [] if grey(image) else infos.get(id(image), []),
        lambda mode, map_name: tracker.new_match(1000.0, "heroselect", mode, map_name),
        lambda: clock[0],
        match_running=lambda: tracker.running,
        on_info=tracker.learn_info,
    )
    reading = reading_mode.ReadingMode(lambda: tracker, lambda: "best", lambda: "light",
                                       lambda: "rapidocr")  # fmt: skip
    hs.update({"heroselect": BANNER, "heroselect_info": first})
    assert (tracker.match_mode, tracker.match_map) == (None, "Busan")
    assert reading.now() == "light"  # unknown queue: the lighter choice (#345)
    clock[0] += IN_MATCH_EVERY_S
    hs.update({"heroselect": BANNER, "heroselect_info": later})
    assert (tracker.match_mode, tracker.match_map) == ("COMPETITIVE", "Busan")
    assert reading.now() == "best"  # its own choice once known
    row = store._read("SELECT mode, map FROM matches WHERE id = ?", (tracker.match_id,))
    assert row == [("COMPETITIVE", "Busan")]  # stored too


def test_only_a_few_more_looks(store):
    looks = []
    hs = HeroSelect(lambda image: "ASSEMBLE YOUR TEAM", lambda image: looks.append(1) or [],
                    lambda mode, map_name: None, lambda: clock[0])  # fmt: skip
    clock = [0.0]
    for _ in range(20):
        hs.update({"heroselect": BANNER, "heroselect_info": glare()})
        clock[0] += IN_MATCH_EVERY_S
    assert len(looks) == 3 * (1 + INFO_TRIES)  # the first look and the retries, 3 variants each


def test_a_known_queue_is_never_overwritten_and_only_hero_select_matches_learn(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(1000.0)
    tracker.learn_info("COMPETITIVE", "Busan")  # no match yet: nothing to learn
    tracker.chat_changed(1001.0)
    tracker.learn_info("COMPETITIVE", "Busan")
    assert tracker.match_mode is None  # a chat start: hero select takes it over, not this
    tracker.new_match(1002.0, "heroselect", "UNRANKED", None)
    tracker.learn_info("COMPETITIVE", "Busan")
    assert (tracker.match_mode, tracker.match_map) == ("UNRANKED", "Busan")

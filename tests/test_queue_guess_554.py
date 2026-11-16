"""A queue hero select couldn't read is the match before's, marked as a guess (#554): "probably
Unranked" in words, counted apart in the evening line, never Competitive, never from a guess."""

import json
import logging

import pytest

from yaptracker.evenings import Evenings, queue_known
from yaptracker.export import export_all
from yaptracker.matches import GUESS_AFTER_S, MatchTracker
from yaptracker.pause import Pause
from yaptracker.reading_mode import ReadingMode
from yaptracker.store.repo import Store
from yaptracker.ui.components import queue_name

T0 = 1_800_000_000.0


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def played(tracker, store, start, mode, end=None):
    tracker.new_match(start, source="heroselect", mode=mode, map_name="Nepal")
    store.add_message(ts=start + 10, channel="match", text="gl", match_id=tracker.match_id)
    tracker.end_match(end or start + 600, "victory")


def source(store, tracker):
    return store._read("SELECT mode, queue_source FROM matches WHERE id = ?",
                       (tracker.match_id,))[0]  # fmt: skip


def test_an_unread_queue_is_the_one_just_before_marked_as_a_guess(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    played(tracker, store, T0, "UNRANKED")
    assert source(store, tracker) == ("UNRANKED", "read")
    tracker.new_match(T0 + 600 + GUESS_AFTER_S - 1, source="heroselect", map_name="Nepal")
    assert source(store, tracker) == ("UNRANKED", "previous")
    status = tracker.status()
    assert (status.mode, status.mode_guessed) == ("UNRANKED", True)
    assert queue_name(status.mode, status.mode_guessed) == "probably Unranked"


@pytest.mark.parametrize("why", ["too long after", "competitive", "the one before a guess"])
def test_no_guess(store, why):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    played(tracker, store, T0, "COMPETITIVE" if why == "competitive" else "UNRANKED")
    after = GUESS_AFTER_S + 1 if why == "too long after" else 60
    if why == "the one before a guess":
        played(tracker, store, T0 + 700, None, T0 + 1200)  # guessed itself
        assert source(store, tracker) == ("UNRANKED", "previous")
        after = 1200 - 600 + 60
    tracker.new_match(T0 + 600 + after, source="heroselect", map_name="Nepal")
    assert source(store, tracker) == (None, None)
    assert not tracker.status().mode_guessed


def test_a_later_read_replaces_the_guess(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    played(tracker, store, T0, "UNRANKED")
    tracker.new_match(T0 + 700, source="heroselect", map_name="Nepal")
    tracker.learn_info("QUICK PLAY", None)  # the camera moved: the title reads after all
    assert source(store, tracker) == ("QUICK PLAY", "read")
    assert not tracker.status().mode_guessed


def test_hero_select_taking_over_a_gap_start_keeps_the_guess_unless_it_reads(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    played(tracker, store, T0, "UNRANKED")
    tracker.chat_changed(T0 + 700)  # lobby chat starts a match
    assert source(store, tracker) == ("UNRANKED", "previous")
    tracker.new_match(T0 + 710, source="heroselect", map_name="Ilios")  # nothing read
    assert source(store, tracker) == ("UNRANKED", "previous")


def test_the_evening_line_counts_read_and_guessed_apart(store, tmp_path, caplog):
    caplog.set_level(logging.INFO, "yaptracker.evenings")
    evenings = Evenings(tmp_path / "evenings.json", store, lambda since: [])
    tracker = MatchTracker(store, Pause(), on_session_end=evenings.record)
    tracker.capture_alive(T0)
    played(tracker, store, T0, "UNRANKED")
    played(tracker, store, T0 + 700, None, T0 + 1300)
    tracker.stop()
    assert "· queue known 50 % (+50 % guessed) ·" in caplog.text
    assert queue_known({"queue": 90.0}) == "90 %"  # older evenings: no guesses counted


def test_the_export_says_which_queues_are_guessed(store, tmp_path):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    played(tracker, store, T0, "UNRANKED")
    played(tracker, store, T0 + 700, None, T0 + 1300)
    data = json.loads(export_all(store, tmp_path, T0 + 2000).read_text(encoding="utf-8"))
    matches = data["sessions"][0]["matches"]
    assert [(m["mode"], m["mode_guessed"]) for m in matches] == [("UNRANKED", False),
                                                                ("UNRANKED", True)]  # fmt: skip


def test_a_guess_never_makes_the_reading_heavier(store):
    """It may be Competitive after all: the lighter of the two choices, as for an unknown one."""
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    played(tracker, store, T0, "UNRANKED")
    tracker.new_match(T0 + 700, source="heroselect", map_name="Nepal")
    reading = ReadingMode(lambda: tracker, lambda: "light", lambda: "best", lambda: "rapidocr")
    assert reading.now() == "light"
    tracker.learn_info("UNRANKED", None)  # read after all: its own choice
    assert reading.now() == "best"


def test_a_competitive_round_after_a_guess_is_the_same_match(store):
    """Unranked, then Competitive whose first hero select wasn't read: the side swap reads it."""
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    played(tracker, store, T0, "UNRANKED")
    tracker.new_match(T0 + 700, source="heroselect", map_name="Nepal")
    first = tracker.match_id
    tracker.new_match(T0 + 1100, source="heroselect", mode="COMPETITIVE", map_name="Nepal")
    assert tracker.match_id == first
    assert source(store, tracker) == ("COMPETITIVE", "read")


def test_a_dropped_hand_start_keeps_the_guess_a_guess(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    played(tracker, store, T0, "UNRANKED")
    tracker.new_match(T0 + 700, source="heroselect", map_name="Nepal")
    tracker.new_match(T0 + 710)  # Start match by hand...
    tracker.end_match(T0 + 720, by_hand=True)  # ...and End match: nothing in it, dropped
    assert tracker.status().mode_guessed


def test_a_restart_mid_match_keeps_the_guess_a_guess(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    played(tracker, store, T0, "UNRANKED")
    tracker.new_match(T0 + 700, source="heroselect", map_name="Nepal")
    tracker.capture_alive(T0 + 730)
    tracker.stop()  # an update
    again = MatchTracker(store, Pause())
    again.capture_alive(T0 + 800)
    assert again.status().mode_guessed


def test_the_markdown_export_says_probably(store, tmp_path):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    played(tracker, store, T0, "UNRANKED")
    played(tracker, store, T0 + 700, None, T0 + 1300)
    export_all(store, tmp_path, T0 + 2000, markdown=True)
    text = next((tmp_path / "days").iterdir()).read_text(encoding="utf-8")
    assert "## Match 1 on Nepal · Unranked · won" in text
    assert "## Match 2 on Nepal · probably Unranked · won" in text

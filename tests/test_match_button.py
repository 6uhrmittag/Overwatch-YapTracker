"""Start match / End match by hand (#269): rarely needed, and it can't leave empty matches.
Real store, fake clock."""

import pytest

from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.store.repo import Store

T0 = 1_000_000.0


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def matches(store):
    return store._read("SELECT source, map, started_at, outcome FROM matches ORDER BY id")


def yap(store, tracker, ts, text="gg"):
    tracker.chat_changed(ts)
    store.add_message(ts=ts, channel="match", text=text, speaker_raw="Pickle",
                      match_id=tracker.match_id)  # fmt: skip


def test_the_button_ends_a_running_match_and_starts_one_otherwise(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    tracker.new_match(T0, source="heroselect", mode="UNRANKED", map_name="PARAISO")
    yap(store, tracker, T0 + 60)
    assert tracker.toggle(T0 + 600) == "ended"  # the end screen was missed
    assert not tracker.running and matches(store) == [("heroselect", "PARAISO", T0, None)]
    assert tracker.toggle(T0 + 700) == "started"
    assert tracker.running


def test_pressing_twice_leaves_nothing(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    tracker.new_match(T0, source="heroselect", map_name="PARAISO")
    yap(store, tracker, T0 + 60)
    tracker.end_match(T0 + 600, outcome="victory")
    tracker.toggle(T0 + 610)
    tracker.toggle(T0 + 613)  # pressed again, nobody typed
    assert matches(store) == [("heroselect", "PARAISO", T0, "victory")]
    assert tracker.status().outcome == "victory" and not tracker.running  # back to Match over


def test_hero_select_soon_after_a_press_is_that_match(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    tracker.toggle(T0)
    tracker.new_match(T0 + 104, source="heroselect", mode="UNRANKED", map_name="EICHENWALDE")
    assert matches(store) == [("heroselect", "EICHENWALDE", T0 + 104, None)]
    assert tracker.status().started_at == T0 + 104


def test_a_press_before_a_long_queue_is_dropped_at_hero_select(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    tracker.toggle(T0)
    tracker.new_match(T0 + 600, source="heroselect", map_name="NEPAL")  # 10 min in the queue
    assert matches(store) == [("heroselect", "NEPAL", T0 + 600, None)]


def test_a_press_with_lobby_chat_is_a_real_match(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    tracker.toggle(T0)
    yap(store, tracker, T0 + 30, "anyone 2 stack?")
    tracker.new_match(T0 + 600, source="heroselect", map_name="NEPAL")
    assert [m[0] for m in matches(store)] == ["hotkey", "heroselect"]


def test_marvs_evening_one_match_per_real_match(store):
    """#251's log, 2026-10-03: the button before every hero select, once pressed twice."""
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    evening = [  # (seconds, what happened)
        (0, "press"), (104, "KING'S ROW"), (650, "victory"),
        (750, "press"), (755, "EICHENWALDE"), (1300, "defeat"),
        (1400, "press"), (1403, "press"), (1600, "PARAISO"), (2100, "victory"),
        (2200, "press"), (2800, "NEPAL"),  # a 10-minute queue after the press
    ]  # fmt: skip
    in_match = None
    for t, what in evening:
        if in_match is not None:  # people chat during a match: every 2 min
            for chat in range(in_match + 60, t, 120):
                yap(store, tracker, T0 + chat)
        tracker.capture_alive(T0 + t)
        if what == "press":
            tracker.toggle(T0 + t)
        elif what in ("victory", "defeat"):
            tracker.end_match(T0 + t, outcome=what)
            in_match = None
        else:
            tracker.new_match(T0 + t, source="heroselect", map_name=what)
            in_match = t
    assert [m[1] for m in matches(store)] == ["KING'S ROW", "EICHENWALDE", "PARAISO", "NEPAL"]
    assert {m[0] for m in matches(store)} == {"heroselect"}

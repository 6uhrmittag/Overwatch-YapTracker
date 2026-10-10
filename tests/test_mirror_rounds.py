"""Competitive Escort and Hybrid rounds stay one match (#364): real store, fake clock."""

import logging

import pytest

from yaptracker import game_lists
from yaptracker.matches import ROUND_MATCH_S, MatchTracker
from yaptracker.pause import Pause
from yaptracker.reading_mode import competitive
from yaptracker.store.repo import Store

T0 = 1_000_000.0
ROUND_S = 6 * 60  # one side attacks, then hero select for the swap


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


@pytest.fixture
def tracker(store):
    t = MatchTracker(store, Pause())
    t.capture_alive(T0)
    return t


def rows(store):
    return store._read("SELECT mode, map, outcome FROM matches ORDER BY id")


def test_map_types_come_with_the_lists():
    assert game_lists.map_type("King's Row") == {"hybrid"}
    assert game_lists.map_type("Route 66") == {"escort"}
    assert game_lists.map_type("Nowhere") == frozenset() == game_lists.map_type(None)


def test_hero_select_on_the_same_map_without_a_result_is_the_next_round(tracker, store, caplog):
    caplog.set_level(logging.INFO, "yaptracker.matches")
    tracker.new_match(T0, "heroselect", "COMPETITIVE", "King's Row")
    tracker.new_match(T0 + ROUND_S, "heroselect", "COMPETITIVE", "King's Row")
    tracker.new_match(T0 + 2 * ROUND_S, "heroselect", None, "King's Row")  # extra round
    assert rows(store) == [("COMPETITIVE", "King's Row", None)]
    assert "match 1: round 3 (same map, no result yet)" in caplog.text
    tracker.end_match(T0 + 3 * ROUND_S, "victory")
    assert rows(store) == [("COMPETITIVE", "King's Row", "victory")]


def test_competitive_escort_with_the_map_unread_is_the_next_round(tracker, store):
    tracker.new_match(T0, "heroselect", "COMPETITIVE", "Route 66")
    tracker.new_match(T0 + ROUND_S, "heroselect", "COMPETITIVE", None)
    tracker.new_match(T0 + 2 * ROUND_S, "heroselect", None, None)  # queue unread too: known
    assert len(rows(store)) == 1


def test_not_a_round(tracker, store):
    tracker.new_match(T0, "heroselect", "COMPETITIVE", "Route 66")
    tracker.end_match(T0 + ROUND_S, "defeat")  # a real result first: always a new match
    tracker.new_match(T0 + ROUND_S + 120, "heroselect", "COMPETITIVE", "Route 66")
    tracker.new_match(T0 + 2 * ROUND_S, "heroselect", "COMPETITIVE", "Havana")  # another map
    tracker.new_match(T0 + 3 * ROUND_S, "heroselect", "UNRANKED", None)  # not Competitive
    late = T0 + 3 * ROUND_S + ROUND_MATCH_S + 1  # same map, but far too late for a round
    tracker.new_match(late, "heroselect", "UNRANKED", "Havana")
    tracker.new_match(late + 60, "heroselect", "COMPETITIVE", "Ilios")  # Control: no mirror
    tracker.new_match(late + 120, "heroselect", "COMPETITIVE", None)
    tracker.new_match(late + 180, "heroselect", "QUICK PLAY", "Ilios")  # same map, other queue
    assert len(rows(store)) == 8


def test_a_mirror_round_makes_an_unread_queue_competitive(tracker, store, caplog):
    caplog.set_level(logging.INFO, "yaptracker.matches")
    tracker.new_match(T0, "heroselect", None, "Eichenwalde")  # queue washed out (#342)
    assert not competitive(tracker.match_mode)
    tracker.new_match(T0 + ROUND_S, "heroselect", None, "Eichenwalde")
    assert competitive(tracker.match_mode)  # the Competitive reading setting applies now
    assert rows(store) == [("COMPETITIVE", "Eichenwalde", None)]
    assert "match 1: Competitive, from a mirror round" in caplog.text


def test_a_control_map_keeps_its_unread_queue(tracker, store):
    """Control has rounds in Quick Play too: a second hero select there proves nothing."""
    tracker.new_match(T0, "heroselect", None, "Ilios")
    tracker.new_match(T0 + ROUND_S, "heroselect", None, "Ilios")
    assert rows(store) == [(None, "Ilios", None)]

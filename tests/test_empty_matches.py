"""Empty matches are hidden everywhere, and a match lasts from its start to its result (#270)."""

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


def test_matches_without_lines_and_result_are_hidden(store):
    session = store.start_session(T0)
    talked = store.start_match(session, T0, "heroselect", map_name="PARAISO")
    store.add_message(ts=T0 + 30, channel="match", text="gg", match_id=talked)
    pressed = store.start_match(session, T0 + 600, "hotkey")  # New match before #269
    store.end_match(pressed, T0 + 610)
    quiet_win = store.start_match(session, T0 + 700, "heroselect", map_name="NEPAL")
    store.end_match(quiet_win, T0 + 1300, "victory")  # nobody typed, but it was played
    assert [m.id for m in store.session_matches(session)] == [talked, quiet_win]
    assert [m[0] for m in store.all_matches()] == [talked, quiet_win]  # the export
    assert store.sessions()[0].matches == 2
    assert store.stats().matches == 2
    assert store.match_number(quiet_win) == 2


def test_the_running_match_counts_itself_before_its_first_line(store):
    session = store.start_session(T0)
    first = store.start_match(session, T0, "heroselect")
    store.add_message(ts=T0 + 30, channel="match", text="hi", match_id=first)
    running = store.start_match(session, T0 + 700, "heroselect")
    assert store.match_number(running) == 2


def test_a_session_of_only_empty_matches_is_not_listed(store):
    session = store.start_session(T0)
    store.start_match(session, T0, "hotkey")
    assert store.sessions() == []


def test_post_match_chat_does_not_stretch_the_match(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    tracker.new_match(T0, source="heroselect", map_name="PARAISO")
    store.add_message(ts=T0 + 60, channel="match", text="hi", match_id=tracker.match_id)
    tracker.end_match(T0 + 552, outcome="victory")
    for t in (560, 590, 620):  # "gg", "gg wp", "ty" after the banner
        tracker.chat_changed(T0 + t)
        store.add_message(ts=T0 + t, channel="match", text="gg", match_id=tracker.match_id)
    (row,) = store.session_matches(tracker.session_id)
    assert (row.started_at, row.ended_at) == (T0, T0 + 552)

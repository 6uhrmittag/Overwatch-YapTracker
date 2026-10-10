"""Matches split in two are merged at the next start: a Competitive side swap (#371), a
quiet chat inside a hero-select match (#377)."""

import json
import logging

import pytest

from yaptracker.later import unread_matches
from yaptracker.matches import LONGEST_MATCH_S, QUIET_GAP_S, ROUND_MATCH_S, merge_split_matches
from yaptracker.store.backups import before_merge
from yaptracker.store.repo import Store

T0 = 1_000_000.0


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def match(store, session, start, map_name, outcome=None, mode=None, lines=1):
    mid = store.start_match(session, start, "heroselect", mode, map_name)
    for n in range(lines):
        store.add_message(ts=start + 10 + n, channel="match", text=f"yap {n}", match_id=mid)
    store.end_match(mid, start + 300, outcome)
    return mid


def rows(store):
    return store._read(
        "SELECT id, map, mode, outcome, loved_at IS NOT NULL FROM matches ORDER BY id"
    )


def lines_of(store, mid):
    return store._read("SELECT COUNT(*) FROM chat_messages WHERE match_id = ?", (mid,))[0][0]


def test_rounds_split_before_become_one_match_with_a_backup_first(store, tmp_path, caplog):
    caplog.set_level(logging.INFO, "yaptracker.matches")
    s = store.start_session(T0)
    first = match(store, s, T0, "King's Row", lines=2)
    second = match(store, s, T0 + 360, "King's Row", lines=3)
    third = match(store, s, T0 + 720, "King's Row", "victory", lines=1)  # an extra round
    store.set_loved(second, T0 + 900)
    newest = match(store, s, T0 + 1500, "Ilios", "defeat")  # the next match: never touched
    backups = []

    def backup():
        backups.append(before_merge(store.backup_to, tmp_path / "backups"))
        return backups[-1]

    assert merge_split_matches(store, set(), backup) == 2
    assert rows(store) == [(first, "King's Row", "COMPETITIVE", "victory", 1),
                           (newest, "Ilios", None, "defeat", 0)]  # fmt: skip
    assert lines_of(store, first) == 6
    assert len(backups) == 1 and backups[0].exists()
    assert f"merged match {second} into {first}: mirror round on King's Row" in caplog.text
    assert third not in [r[0] for r in rows(store)]


def test_the_result_comes_from_the_last_round(store):
    s = store.start_session(T0)
    first = match(store, s, T0, "Route 66", mode="COMPETITIVE")
    match(store, s, T0 + 360, "Route 66", "defeat", mode="COMPETITIVE")
    match(store, s, T0 + 900, "Havana")
    merge_split_matches(store, set(), lambda: "backup")
    assert rows(store)[0][:4] == (first, "Route 66", "COMPETITIVE", "defeat")


def test_what_is_never_merged(store):
    s = store.start_session(T0)
    match(store, s, T0, "Route 66", "victory")  # a result: the next one is a new match
    match(store, s, T0 + 360, "Route 66")
    match(store, s, T0 + 360 + ROUND_MATCH_S + 1, "Route 66")  # too late for a round
    match(store, s, T0 + 4000, "Havana", mode="QUICK PLAY")
    match(store, s, T0 + 4300, "Havana", mode="COMPETITIVE")  # two queues, both read
    match(store, s, T0 + 5000, "Ilios")
    other = store.start_session(T0 + 9000)
    match(store, other, T0 + 9000, "Ilios")  # another session
    kept_a = match(store, other, T0 + 9500, "Busan")
    match(store, other, T0 + 9800, "Busan")  # waits for unread frames (#349)
    match(store, other, T0 + 10500, "Oasis")
    match(store, other, T0 + 10800, "Oasis")  # the newest: it may go on after a restart
    before = rows(store)
    called = []
    assert merge_split_matches(store, {kept_a}, lambda: called.append(1)) == 0
    assert rows(store) == before and not called  # nothing merged: no backup either


def quiet_split(store, session, start, quiet=QUIET_GAP_S + 10, outcome="defeat", mode="UNRANKED"):
    """#377 before its fix: hero select, "gl hf", nobody typed for 5 min, the next line started
    a 'gap' match. The tracker closed the first at its last line."""
    first = store.start_match(session, start, "heroselect", mode, None)
    store.add_message(ts=start + 30, channel="match", text="gl hf", match_id=first)
    store.end_match(first, start + 30)
    second = store.start_match(session, start + 30 + quiet, "gap")
    for n in range(3):
        store.add_message(ts=start + 30 + quiet + n, channel="team", text="swap", match_id=second)
    store.end_match(second, start + 30 + quiet + 240, outcome)
    return first, second


def test_a_match_a_quiet_chat_split_is_one_match_again(store, caplog):
    caplog.set_level(logging.INFO, "yaptracker.matches")
    s = store.start_session(T0)
    first, second = quiet_split(store, s, T0)
    newest = match(store, s, T0 + 1500, "Ilios", "victory")
    assert merge_split_matches(store, set(), lambda: "backup") == 1
    assert rows(store) == [(first, None, "UNRANKED", "defeat", 0),
                           (newest, "Ilios", None, "victory", 0)]  # fmt: skip
    assert lines_of(store, first) == 4
    assert f"merged match {second} into {first}: split by a quiet chat" in caplog.text


def test_what_a_quiet_chat_didnt_split(store):
    s = store.start_session(T0)
    quiet_split(store, s, T0, quiet=QUIET_GAP_S - 10)  # less than 5 min: another cause
    quiet_split(store, s, T0 + 2000, quiet=LONGEST_MATCH_S)  # too long for one match
    ended = match(store, s, T0 + 5000, None)  # its end screen showed, outcome unread
    store.start_match(s, T0 + 5000 + 300 + QUIET_GAP_S, "gap")
    by_hand = store.start_match(s, T0 + 7000, "heroselect")
    store.add_message(ts=T0 + 7010, channel="match", text="gl hf", match_id=by_hand)
    store.end_match(by_hand, T0 + 7200)  # End match pressed after its last line
    store.start_match(s, T0 + 7200 + QUIET_GAP_S, "gap")
    first, _ = quiet_split(store, s, T0 + 9000)
    store.start_match(s, T0 + 9900, "heroselect")  # newest: only `keep` holds the pair back
    before = rows(store)
    assert merge_split_matches(store, {first}, lambda: "backup") == 0  # waits to be read
    assert rows(store) == before and ended in [r[0] for r in before]


def test_unread_matches_come_from_the_index_only(tmp_path):
    unread = tmp_path / "unread"
    assert unread_matches(unread) == set()
    unread.mkdir()
    (unread / "index.json").write_text(json.dumps(
        [{"since": 1, "ts": 1, "file": "0.npy", "match": 7, "mode": "after"},
         {"since": 2, "ts": 2, "file": "1.npy", "match": None, "mode": "after"}]))  # fmt: skip
    assert unread_matches(unread) == {7}
    (unread / "index.json").write_text("cut off mid-wri")
    assert unread_matches(unread) == set()

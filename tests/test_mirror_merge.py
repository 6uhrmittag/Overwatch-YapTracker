"""Matches split at a Competitive side swap are merged at the next start (#371)."""

import json
import logging

import pytest

from yaptracker.later import unread_matches
from yaptracker.matches import ROUND_MATCH_S, merge_mirror_rounds
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

    assert merge_mirror_rounds(store, set(), backup) == 2
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
    merge_mirror_rounds(store, set(), lambda: "backup")
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
    assert merge_mirror_rounds(store, {kept_a}, lambda: called.append(1)) == 0
    assert rows(store) == before and not called  # nothing merged: no backup either


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

import sqlite3
import threading

import pytest

from yaptracker.store import db, schema
from yaptracker.store.repo import Store


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def test_a_new_database_has_schema_v1_in_wal_mode(tmp_path):
    conn = db.connect(tmp_path / "yaptracker.db", tmp_path / "backups")
    assert db.version(conn) == db.LATEST == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"sessions", "matches", "players", "player_aliases", "chat_messages", "capture_gaps",
            "chat_fts"} <= tables  # fmt: skip
    assert not (tmp_path / "backups").exists()  # nothing to back up yet


def test_messages_are_stored_per_match_and_found_by_full_text_search(store):
    session = store.start_session(1000.0)
    match = store.start_match(session, 1001.0, "heroselect")
    store.add_message(ts=1002.0, channel="match", speaker_raw="NoodleBonk", text="WAHOOOO",
                      match_id=match, ocr_confidence=0.97)  # fmt: skip
    store.add_message(ts=1003.0, channel="team", speaker_raw="SirPeelsALot", hero="Reinhardt",
                      text="Group up!", match_id=match)  # fmt: skip
    assert [m.text for m in store.messages(match)] == ["WAHOOOO", "Group up!"]
    assert [m.speaker_raw for m in store.search("group")] == ["SirPeelsALot"]
    assert [m.text for m in store.search("noodlebonk")] == ["WAHOOOO"]  # speakers are searchable
    assert store.search('"; DROP TABLE chat_messages; --') == []  # just words, never syntax
    assert store.stats().messages == 2 and store.stats().matches == 1


def test_values_outside_the_data_model_are_refused(store):
    session = store.start_session(1.0)
    with pytest.raises(sqlite3.IntegrityError):
        store.start_match(session, 2.0, "guess")
    with pytest.raises(sqlite3.IntegrityError):
        store.add_message(ts=1.0, channel="match", text="hi", flagged="maybe")


def test_gaps_are_recorded(store):
    gap = store.open_gap(10.0, "window_lost")
    store.close_gap(gap, 25.0)
    with pytest.raises(sqlite3.IntegrityError):
        store.open_gap(30.0, "because")


def test_a_migration_backs_up_the_database_first(tmp_path, monkeypatch):
    path, backups = tmp_path / "yaptracker.db", tmp_path / "backups"
    store = Store.open(path, backups)
    store.add_message(ts=1.0, channel="match", text="before the update")
    store.close()

    monkeypatch.setattr(db, "MIGRATIONS", [*schema.MIGRATIONS, "ALTER TABLE players ADD COLUMN x;"])
    monkeypatch.setattr(db, "LATEST", 2)
    conn = db.connect(path, backups)
    assert db.version(conn) == 2
    (copy,) = backups.iterdir()
    assert copy.name.startswith("yaptracker-v1-")
    with sqlite3.connect(copy) as old:
        assert old.execute("SELECT text FROM chat_messages").fetchall() == [("before the update",)]
        assert old.execute("SELECT version FROM schema_version").fetchone() == (1,)


def test_a_database_from_a_newer_app_is_never_touched(tmp_path):
    path = tmp_path / "yaptracker.db"
    conn = db.connect(path, tmp_path / "backups")
    conn.execute("UPDATE schema_version SET version = 99")
    conn.close()
    with pytest.raises(db.NewerDatabaseError):
        db.connect(path, tmp_path / "backups")


def test_capture_and_ui_threads_can_write_at_the_same_time(store):
    def write(n):
        for i in range(50):
            store.add_message(ts=float(i), channel="match", text=f"yap {n}-{i}")

    threads = [threading.Thread(target=write, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert store.stats().messages == 200

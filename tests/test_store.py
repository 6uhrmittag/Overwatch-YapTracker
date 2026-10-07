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


def test_a_new_database_has_the_latest_schema_in_wal_mode(tmp_path):
    conn = db.connect(tmp_path / "yaptracker.db", tmp_path / "backups")
    assert db.version(conn) == db.LATEST == 8  # gaps of chat kept for later (#335)
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

    latest = db.LATEST
    monkeypatch.setattr(db, "MIGRATIONS", [*schema.MIGRATIONS, "ALTER TABLE players ADD COLUMN x;"])
    monkeypatch.setattr(db, "LATEST", latest + 1)
    conn = db.connect(path, backups)
    assert db.version(conn) == latest + 1
    (copy,) = backups.iterdir()
    assert copy.name.startswith(f"yaptracker-v{latest}-")
    with sqlite3.connect(copy) as old:
        assert old.execute("SELECT text FROM chat_messages").fetchall() == [("before the update",)]
        assert old.execute("SELECT version FROM schema_version").fetchone() == (latest,)


def test_a_v1_database_gets_the_role_column_and_keeps_its_yaps(tmp_path, monkeypatch):
    path, backups = tmp_path / "yaptracker.db", tmp_path / "backups"
    with monkeypatch.context() as v1_app:  # what's on Marv's PC since #92
        v1_app.setattr(db, "MIGRATIONS", schema.MIGRATIONS[:1])
        v1_app.setattr(db, "LATEST", 1)
        old = db.connect(path, backups)
        old.execute("INSERT INTO chat_messages (ts, channel, text) VALUES (1.0, 'match', 'gg')")
        old.close()
    store = Store.open(path, backups)
    store.add_message(ts=2.0, channel="team", speaker_raw="tortillaTank", text="hi", role="me")
    assert [(m.text, m.role) for m in store.search("gg") + store.search("hi")] == [
        ("gg", None),
        ("hi", "me"),
    ]
    with pytest.raises(sqlite3.IntegrityError):
        store.add_message(ts=3.0, channel="match", text="x", role="boss")
    store.close()
    assert len(list(backups.iterdir())) == 1


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


def test_a_v2_database_gets_has_glyphs_and_keeps_its_yaps(tmp_path, monkeypatch):
    path, backups = tmp_path / "yaptracker.db", tmp_path / "backups"
    with monkeypatch.context() as v2_app:  # what's on Marv's PC since #109
        v2_app.setattr(db, "MIGRATIONS", schema.MIGRATIONS[:2])
        v2_app.setattr(db, "LATEST", 2)
        old = db.connect(path, backups)
        old.execute("INSERT INTO chat_messages (ts, channel, text) VALUES (1.0, 'match', 'gg')")
        old.close()
    store = Store.open(path, backups)
    store.add_message(ts=2.0, channel="match", text="gg ◇", has_glyphs=True)
    assert [(m.text, m.has_glyphs) for m in store.search("gg")] == [("gg", 0), ("gg ◇", 1)]
    store.close()


def test_friend_list_notices_stored_as_chat_become_system_lines(tmp_path, monkeypatch):
    """#306: rows from before the fix; a line fixed by hand stays as it is."""
    INSERT = ("INSERT INTO chat_messages (ts, channel, speaker_raw, player_id, text, edited_at) "
              "VALUES (1.0, ?, ?, 1, ?, ?)")  # fmt: skip
    path, backups = tmp_path / "yaptracker.db", tmp_path / "backups"
    with monkeypatch.context() as v6_app:
        v6_app.setattr(db, "MIGRATIONS", schema.MIGRATIONS[:6])
        v6_app.setattr(db, "LATEST", 6)
        old = db.connect(path, backups)
        old.execute("INSERT INTO players (id, display_name) VALUES (1, 'Pal')")
        for speaker, text, edited in (("Pal", "stopped playing Overwatch.", None),
                                      ("Pal", "started spectating.", None),
                                      ("Pal", "stopped playing Overwatch.", 5.0),
                                      ("Pal", "stopped playing? no way", None)):  # fmt: skip
            old.execute(INSERT, ("team", speaker, text, edited))
        old.execute(INSERT, ("system", "Pal", "[Pal] joined the game.", None))
        old.close()
    store = Store.open(path, backups)
    rows = store._read("SELECT channel, player_id, text FROM chat_messages ORDER BY id")
    assert rows == [
        ("system", None, "[Pal] stopped playing Overwatch."),
        ("system", None, "[Pal] started spectating."),
        ("team", 1, "stopped playing Overwatch."),  # edited by hand
        ("system", None, "[Pal] stopped playing? no way"),
        ("system", None, "[Pal] joined the game."),  # no match met together
    ]
    assert [m.text for m in store.search("spectating")] == ["[Pal] started spectating."]
    store.close()


def test_gaps_keep_their_rows_and_learn_the_lost_frames_reason(tmp_path, monkeypatch):
    """#335: v7 -> v8 copies capture_gaps over to allow 'deferred_lost'."""
    path, backups = tmp_path / "yaptracker.db", tmp_path / "backups"
    with monkeypatch.context() as v7_app:
        v7_app.setattr(db, "MIGRATIONS", schema.MIGRATIONS[:7])
        v7_app.setattr(db, "LATEST", 7)
        old = db.connect(path, backups)
        old.execute("INSERT INTO capture_gaps (started_at, ended_at, reason) "
                    "VALUES (1.0, 2.0, 'paused')")  # fmt: skip
        old.close()
    store = Store.open(path, backups)
    store.close_gap(store.open_gap(3.0, "deferred_lost"), 4.0)
    assert store.all_gaps() == [(1.0, 2.0, "paused"), (3.0, 4.0, "deferred_lost")]
    assert list(backups.iterdir())  # backed up before migrating
    store.close()

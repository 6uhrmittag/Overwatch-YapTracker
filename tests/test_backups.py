"""Daily backups (#125): once a day, never while capturing, 7 daily + 4 weekly kept."""

import sqlite3
from datetime import date, timedelta

import pytest

from yaptracker.store.backups import DailyBackup, daily_backups, last_backup, prune
from yaptracker.store.repo import Store

TODAY = date(2026, 10, 1)


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "migration-backups")
    yield s
    s.close()


def test_one_backup_a_day_with_everything_in_it(store, tmp_path):
    store.add_message(ts=1.0, channel="match", text="gg")
    backups = DailyBackup(store.backup_to, tmp_path / "backups", busy=lambda: False,
                          today=lambda: TODAY)  # fmt: skip
    first = backups.run_once()
    assert first.name == "yaptracker-2026-10-01.db"
    with sqlite3.connect(first) as copy:
        assert copy.execute("SELECT text FROM chat_messages").fetchall() == [("gg",)]
    assert backups.run_once() is None  # already done today


def test_never_while_overwatch_is_being_captured(store, tmp_path):
    capturing = {"now": True}
    backups = DailyBackup(store.backup_to, tmp_path / "backups",
                          busy=lambda: capturing["now"], today=lambda: TODAY)  # fmt: skip
    assert backups.run_once() is None
    capturing["now"] = False  # Overwatch closed: the next check backs up
    assert backups.run_once() is not None


def test_seven_days_and_four_weeks_are_kept_and_migration_backups_never_touched(tmp_path):
    folder = tmp_path / "backups"
    folder.mkdir()
    for n in range(60):
        (folder / f"yaptracker-{(TODAY - timedelta(days=n)).isoformat()}.db").write_bytes(b"x")
    (folder / "yaptracker-v1-20260930-120000.db").write_bytes(b"x")
    prune(folder)
    days = [day for day, _ in daily_backups(folder)]
    assert days[:7] == [TODAY - timedelta(days=n) for n in range(7)]
    weeks = {day.isocalendar()[:2] for day in days}
    assert len(days) == 9 and len(weeks) == 4  # 7 days span two weeks, plus two older Sundays
    assert (folder / "yaptracker-v1-20260930-120000.db").exists()


def test_settings_says_when_the_last_backup_was(tmp_path):
    assert last_backup(tmp_path) is None
    (tmp_path / "yaptracker-2026-10-01.db").write_bytes(b"x")
    (tmp_path / "yaptracker-2026-09-30.db").write_bytes(b"x")
    assert last_backup(tmp_path)[1] == 2

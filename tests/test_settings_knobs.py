"""Settings (#152): OCR engine, how often chat is read, open data folder, back up now."""

import time
from datetime import date

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, paths, runtime
from yaptracker.store.backups import DailyBackup, daily_backups
from yaptracker.store.repo import Store
from yaptracker.ui import shell


def test_read_gap_persists_and_only_known_values_count():
    assert config.read_every_s() == 1.5
    config.save_read_every_s(3.0)
    assert config.read_every_s() == 3.0
    config.save_read_every_s(0.1)  # a hand-edited config.json can't make it hammer the CPU
    assert config.read_every_s() == 1.5


def test_back_up_now_even_during_a_match_and_again_the_same_day(tmp_path):
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        backups = DailyBackup(store.backup_to, tmp_path / "out", busy=lambda: True,
                              today=lambda: date(2026, 10, 1))  # fmt: skip
        assert backups.run_once() is None  # the automatic one waits for a quiet moment
        first = backups.now()
        assert first.name == "yaptracker-2026-10-01.db"
        store.add_message(ts=1.0, channel="match", text="gg")
        backups.now()  # replaces today's copy
        assert [p.name for _, p in daily_backups(tmp_path / "out")] == [first.name]
    finally:
        store.close()


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


class FakeReader:
    min_gap_s = 1.5


async def test_reading_card_changes_apply_at_once(user: User, monkeypatch):
    config.save_setup_state("done")
    reader = FakeReader()
    monkeypatch.setattr(runtime, "reader", reader)
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("Read the chat")
    user.find(marker="gap-3.0").click()
    assert reader.min_gap_s == 3.0 and config.read_every_s() == 3.0
    user.find(marker="engine-rapidocr").click()
    assert config.ocr_engine() == "rapidocr"


async def test_back_up_now_button(user: User, monkeypatch, tmp_path):
    config.save_setup_state("done")
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        monkeypatch.setattr(runtime, "store", store)
        backups = DailyBackup(store.backup_to, paths.backup_dir(), busy=lambda: True)
        monkeypatch.setattr(runtime, "backups", backups)
        await user.open("/")
        user.find(marker="nav-settings").click()
        await user.should_see("No daily backup yet")
        user.find(marker="backup-now").click()
        await user.should_see(f"Last backup: today {time.strftime('%H:%M')}")
        assert daily_backups(paths.backup_dir())
        await user.should_see("Open data folder")
    finally:
        store.close()

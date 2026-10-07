"""An older YapTracker on a newer database (#352): it says so in words and touches nothing."""

import hashlib

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import runtime
from yaptracker.store import db
from yaptracker.store.repo import Store
from yaptracker.ui import shell


def test_a_newer_database_is_refused_and_left_as_it_was(tmp_path):
    path = tmp_path / "yaptracker.db"
    Store.open(path, tmp_path / "backups").close()
    conn = db.connect(path, tmp_path / "backups")
    conn.execute(f"UPDATE schema_version SET version = {db.LATEST + 1}")
    conn.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(db.NewerDatabaseError, match="Update the app"):
        Store.open(path, tmp_path / "backups")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert not (tmp_path / "backups").exists()  # no backup, no migration


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_the_window_says_it_in_words(user: User, monkeypatch):
    monkeypatch.setattr(runtime, "data_too_new", "yaptracker.db has schema v9, this "
                        "YapTracker only knows v8. Update the app.")  # fmt: skip
    await user.open("/")
    await user.should_see("Your data is from a newer YapTracker")
    await user.should_see("Run tools/update.ps1")
    await user.should_not_see(marker="nav-live")  # nothing else runs

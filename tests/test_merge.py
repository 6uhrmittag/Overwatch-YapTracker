"""Merge two players (#28): OCR made two of one person; merging loses nothing and can be undone."""

import time

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, paths, runtime
from yaptracker.players import PlayerMatcher
from yaptracker.store.backups import before_merge
from yaptracker.store.repo import Store
from yaptracker.ui import shell


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def two_of_one(store):
    """'magin' and its misread 'mao' became two players."""
    right, wrong = store.add_player("magin", 100.0), store.add_player("mao", 50.0)
    store.add_alias(wrong, "maoo")
    store.set_notes(right, "Zen main, calls targets.")
    store.set_notes(wrong, "Said gl hf.")
    store.set_verdict(wrong, "fun")
    for pid, text in [(right, "Group up!"), (wrong, "gl hf")]:
        store.add_message(ts=60.0, channel="match", text=text, speaker_raw="x", player_id=pid)
    return right, wrong


def test_merging_keeps_yaps_notes_spellings_verdict_and_dates(store):
    right, wrong = two_of_one(store)
    store.merge_players(wrong, right)
    assert [p.display_name for p in store.players()] == ["magin"]
    merged = store.player(right)
    assert merged.yaps == 2
    assert merged.notes == "Zen main, calls targets.\n\nSaid gl hf."  # joined, not lost
    assert merged.verdict == "fun"  # magin had none: taken over
    assert (merged.first_seen, merged.last_seen) == (50.0, 100.0)
    assert store.aliases(right) == ["mao", "maoo"]


def test_a_verdict_you_gave_the_kept_one_stays(store):
    right, wrong = two_of_one(store)
    store.set_verdict(right, "friend")
    store.merge_players(wrong, right)
    assert store.player(right).verdict == "friend"


def test_a_backup_comes_first_and_new_lines_find_the_merged_player(store, tmp_path):
    right, wrong = two_of_one(store)
    matcher = PlayerMatcher(store)
    backup = before_merge(store.backup_to, tmp_path / "merge-backups")
    store.merge_players(wrong, right)
    matcher.reload()
    assert backup.exists() and backup.name.startswith("yaptracker-before-merge-")
    assert matcher.link("mao", 200.0) == right  # the misread now lands on magin


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_merge_from_the_profile(user: User, store, monkeypatch):
    config.save_setup_state("done")
    right, wrong = two_of_one(store)
    store.player_seen(wrong, time.time())  # newest, so first in the list
    monkeypatch.setattr(runtime, "store", store)
    await user.open("/")
    user.find(marker="nav-yappers").click()
    user.find(marker=f"yapper-{wrong}").click()
    await user.should_see("Your verdict")
    user.find(marker="merge").click()
    user.find(marker="merge-search").type("magin")
    user.find(marker="merge-pick").click()
    await user.should_see("mao → magin?")
    user.find(marker="merge-ok").click()
    await user.should_see("Also read as mao, maoo")
    assert [p.display_name for p in store.players()] == ["magin"]
    assert list(paths.backup_dir().glob("yaptracker-before-merge-*.db"))

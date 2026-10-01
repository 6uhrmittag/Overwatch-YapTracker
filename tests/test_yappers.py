"""Yappers (#24): everyone you've met, filtered, sorted and found by a sloppy name."""

import time

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.store.repo import Store
from yaptracker.ui import shell
from yaptracker.ui.components import when

NOW = time.time()


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


@pytest.fixture(autouse=True)
def _set_up():
    config.save_setup_state("done")


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    session = s.start_session(NOW - 86400 * 3)
    for name, verdict, matches, days_ago in [("NoodleBonk", "friend", 3, 0),
                                             ("gremlin.exe", "avoid", 1, 1),
                                             ("SirPeelsALot", None, 2, 10)]:  # fmt: skip
        pid = s.add_player(name, NOW - 86400 * days_ago)
        if verdict:
            s.set_verdict(pid, verdict)
        for m in range(matches):
            match = s.start_match(session, NOW - 86400 * days_ago - m, "gap")
            s.add_message(ts=NOW - 86400 * days_ago, channel="match", text="gg", match_id=match,
                          speaker_raw=name, player_id=pid)  # fmt: skip
    s.add_alias(1, "NoodleBonkl")
    monkeypatch.setattr(runtime, "store", s)
    yield s
    s.close()


def names(user: User) -> list[str]:
    """The names in the order they're shown."""
    (body,) = user.find(marker="yapper-list").elements
    rows = [row for row in body.default_slot.children if "yapper" in row._markers]
    return [row.default_slot.children[0].text for row in rows]


async def test_nobody_yet(user: User):
    await user.open("/")
    user.find(marker="nav-yappers").click()
    await user.should_see("Nobody yet")
    await user.should_see("Play a match and the people who yap will show up here.")


async def test_everyone_with_stickers_newest_first(user: User, store):
    await user.open("/")
    user.find(marker="nav-yappers").click()
    await user.should_see("3 met")
    assert names(user) == ["NoodleBonk", "gremlin.exe", "SirPeelsALot"]
    await user.should_see("Bestie")
    await user.should_see("Nope")
    await user.should_see("last met today · 3 matches · 3 yaps")


async def test_filter_and_sort(user: User, store):
    await user.open("/")
    user.find(marker="nav-yappers").click()
    user.find(marker="filter-avoid").click()
    await user.should_see("gremlin.exe")
    assert names(user) == ["gremlin.exe"]
    user.find(marker="filter-none").click()
    assert names(user) == ["SirPeelsALot"]
    user.find(marker="filter-all").click()
    user.find(marker="sort-times").click()
    assert names(user) == ["NoodleBonk", "SirPeelsALot", "gremlin.exe"]


async def test_search_finds_sloppy_names_and_aliases(user: User, store):
    await user.open("/")
    user.find(marker="nav-yappers").click()
    user.find(marker="yapper-search").type("noodel")
    await user.should_see("NoodleBonk")
    assert names(user) == ["NoodleBonk"]
    user.find(marker="yapper-search").clear().type("bonkl")  # only the alias has the l
    assert names(user) == ["NoodleBonk"]
    user.find(marker="yapper-search").clear().type("zzzz")
    await user.should_see("Never met them.")


async def test_crew_is_marked(user: User, store):
    config.save_identity([], ["SirPeelsALot"])
    await user.open("/")
    user.find(marker="nav-yappers").click()
    await user.should_see("crew")


def test_last_met_in_plain_words():
    now = time.mktime((2026, 10, 1, 21, 0, 0, 0, 0, -1))  # a Thursday evening
    day = 86400
    assert when(now - 3600, now) == "today"
    assert when(now - day, now) == "yesterday"
    assert when(now - 2 * day, now) == "Tuesday"
    assert when(now - 10 * day, now) == "Sep 21"
    assert when(None, now) == "never"

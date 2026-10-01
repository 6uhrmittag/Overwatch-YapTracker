"""Comms-wheel callouts (#182): kept, but not counted as yaps and out of the way by default."""

import time

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.familiar import FamiliarFaces
from yaptracker.store.repo import Store
from yaptracker.ui import shell

NOW = time.time()


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def evening(store):
    """Kiri typed twice in match 1 and spammed the comms wheel; match 2 is now."""
    session = store.start_session(NOW - 3600)
    kiri = store.add_player("KiriMain", NOW - 3600)
    first = store.start_match(session, NOW - 3600, "heroselect")
    store.add_message(ts=NOW - 3500, channel="match", text="gl hf", speaker_raw="KiriMain",
                      player_id=kiri, match_id=first)  # fmt: skip
    for n, (hero, text) in enumerate([("Kiriko", "Enemy Sombra!")] * 4 + [("Lúcio", "Hello!")]):
        store.add_message(ts=NOW - 3400 + n, channel="team", text=text, speaker_raw="KiriMain",
                          hero=hero, player_id=kiri, match_id=first)  # fmt: skip
    store.add_message(ts=NOW - 3000, channel="match", text="that sombra again lol",
                      speaker_raw="KiriMain", player_id=kiri, match_id=first)  # fmt: skip
    return kiri, store.start_match(session, NOW - 60, "heroselect")


def test_typed_lines_are_yaps_callouts_count_apart(store):
    kiri, now = evening(store)
    player = store.player(kiri)
    assert (player.yaps, player.callouts, player.matches) == (2, 5, 1)
    assert [m.text for m in store.player_messages(kiri)] == ["that sombra again lol", "gl hf"]
    assert len(store.player_messages(kiri, callouts=True)) == 7
    assert store.player_heroes(kiri) == ["Kiriko", "Lúcio"]  # most used first
    assert store.met_before(kiri, now)[:2] == (1, 2)  # one match together, two yaps


def test_search_leaves_callouts_out_unless_asked(store):
    evening(store)
    assert [h.message.text for h in store.find("sombra")] == ["that sombra again lol"]
    assert len(store.find("sombra", callouts=True)) == 5


def test_a_callout_still_brings_the_card_with_the_typed_count(store):
    kiri, now = evening(store)
    card = FamiliarFaces(store).heard(kiri, now)  # their first line now: "Enemy Sombra!"
    assert card is not None and card.yaps == 2


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_profile_hides_callouts_until_you_ask(user: User, store, monkeypatch):
    config.save_setup_state("done")
    kiri, _ = evening(store)
    monkeypatch.setattr(runtime, "store", store)
    await user.open("/")
    user.find(marker="nav-yappers").click()
    user.find(marker=f"yapper-{kiri}").click()
    await user.should_see("Seen as Kiriko, Lúcio")
    await user.should_see("2 yaps in total")
    await user.should_not_see("Enemy Sombra!")
    user.find(marker="show-callouts").click()
    await user.should_see("Enemy Sombra!")
    await user.should_see("as Kiriko")
    await user.should_see("2 yaps in total")  # callouts still don't count


async def test_search_switch_for_callouts(user: User, store, monkeypatch):
    config.save_setup_state("done")
    evening(store)
    monkeypatch.setattr(runtime, "store", store)
    await user.open("/")
    user.find(marker="nav-search").click()
    user.find(marker="search-box").type("sombra")
    await user.should_see("1 yap")
    user.find(marker="search-callouts").click()
    await user.should_see("5 yaps")

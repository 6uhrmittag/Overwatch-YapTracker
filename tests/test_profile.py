"""A yapper's profile (#25): verdict in one click, notes that save themselves, their yaps."""

import time

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.store.repo import Store
from yaptracker.ui import shell
from yaptracker.ui.profile import yap_level

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
    session = s.start_session(NOW - 7200)
    pid = s.add_player("NoodleBonk", NOW - 7200)
    s.add_alias(pid, "NoodleBonkl")
    for n, texts in enumerate([["WAHOOOO", "it is literally the first fight"], ["gg wp"]]):
        match = s.start_match(session, NOW - 7200 + n * 1800, "heroselect")
        for i, text in enumerate(texts):
            s.add_message(ts=NOW - 7200 + n * 1800 + i, channel="match", text=text,
                          match_id=match, speaker_raw="NoodleBonk", player_id=pid)  # fmt: skip
    monkeypatch.setattr(runtime, "store", s)
    yield s
    s.close()


async def open_profile(user: User) -> None:
    await user.open("/")
    user.find(marker="nav-yappers").click()
    user.find(marker="yapper").click()
    await user.should_see("Your verdict")


async def test_a_click_opens_who_they_are(user: User, store):
    await open_profile(user)
    await user.should_see("Also read as NoodleBonkl")
    await user.should_see("matches together")
    await user.should_see("Casual yapper")  # 3 yaps in 2 matches
    await user.should_see("it is literally the first fight")
    await user.should_see("Match 2")  # grouped by match
    user.find(marker="back-to-yappers").click()
    await user.should_see("1 met")


async def test_verdict_in_one_click_and_again_to_take_it_back(user: User, store):
    await open_profile(user)
    user.find(marker="verdict-friend").click()
    assert store.player(1).verdict == "friend"
    user.find(marker="verdict-avoid").click()
    assert store.player(1).verdict == "avoid"
    user.find(marker="verdict-avoid").click()
    assert store.player(1).verdict is None


async def test_notes_save_themselves(user: User, store):
    await open_profile(user)
    user.find(marker="notes").type("Hype Lucio. Greet with a wahoo.")
    await user.should_see("Saved")
    assert store.player(1).notes == "Hype Lucio. Greet with a wahoo."


def test_the_yap_o_meter():
    assert yap_level(0, 3)[0] == "Silent type"
    assert yap_level(4, 2)[0] == "Casual yapper"
    assert yap_level(15, 3)[0] == "Certified yapper"
    assert yap_level(90, 5) == ("Yap lord", 1.0)

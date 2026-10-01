"""Who's that? (#27): type a name from the scoreboard, see who it is, or add them."""

import time

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.store.repo import Store
from yaptracker.ui import shell
from yaptracker.ui.yappers import matching


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
    s.set_verdict(s.add_player("NoodleBonk", time.time()), "friend")
    s.add_player("gremlin.exe", time.time())
    monkeypatch.setattr(runtime, "store", s)
    yield s
    s.close()


async def test_a_name_from_the_scoreboard_finds_them(user: User, store):
    await user.open("/")
    await user.should_see("Who's that?")
    await user.should_see("Ctrl Alt F")  # the hotkey, shown on the box
    user.find(marker="lookup-box").type("noodlebnk")
    await user.should_see("Bestie")
    user.find(marker="lookup-result").click()
    await user.should_see("Your verdict")  # their profile


async def test_never_met_them_can_be_added(user: User, store):
    await user.open("/")
    user.find(marker="lookup-box").type("SirPeelsALot")
    await user.should_see("Never met them. Want to add them?")
    user.find(marker="lookup-add").click()
    await user.should_see("Your verdict")
    assert "SirPeelsALot" in [p.display_name for p in store.players()]


async def test_ctrl_alt_f_opens_live_with_the_box_from_any_view(user: User, store):
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("Settings")
    runtime.lookup_requested = time.monotonic()  # what the hotkey does
    await user.should_see("Who's that?", retries=50)


def test_results_come_fast_even_with_lots_of_yappers(tmp_path):
    store = Store.open(tmp_path / "many.db", tmp_path / "backups")
    for n in range(500):
        pid = store.add_player(f"Player{n:03d}xyz", float(n))
        store.add_alias(pid, f"PIayer{n:03d}xyz")
    players, names = store.players(), store.player_names()
    started = time.perf_counter()
    found = matching(players, names, "player123")
    assert (time.perf_counter() - started) < 0.1  # < 100 ms
    assert found[0].display_name == "Player123xyz"
    store.close()

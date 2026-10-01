"""My crew is a list (#162): Enter, Add or clicking away adds a name; nothing typed is lost."""

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config
from yaptracker.familiar import FamiliarFaces
from yaptracker.store.repo import Store
from yaptracker.ui import shell


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_three_crew_names_three_ways_and_none_gets_a_card(user: User, tmp_path):
    config.save_setup_state("done")
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("as many as you like")
    user.find(marker="add-crew").trigger("keydown.enter", "Void")
    await user.should_see(marker="remove-Void")
    user.find(marker="add-crew").trigger("blur", "Mossyfox")  # typed, then clicked elsewhere
    await user.should_see(marker="remove-Mossyfox")
    user.find(marker="add-crew-button").trigger("click", "Bapricot")
    await user.should_see(marker="remove-Bapricot")
    user.find(marker="add-crew").trigger("blur", "")  # nothing typed: nothing added
    (field,) = user.find(marker="add-crew").elements
    assert field.props["placeholder"] == "Add another…"

    crew = config.identity().crew  # read fresh from config.json, as after a restart
    assert crew == ("Void", "Mossyfox", "Bapricot")
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        session = store.start_session(1.0)
        old = store.start_match(session, 1.0, "gap")
        now = store.start_match(session, 100.0, "gap")
        faces = FamiliarFaces(store, config.identity)
        for name in crew:
            pid = store.add_player(name, 1.0)
            store.add_message(ts=2.0, channel="team", text="gg", speaker_raw=name, player_id=pid,
                              match_id=old)  # fmt: skip
            assert faces.heard(pid, now) is None, name  # crew is never "Look who's back!"
    finally:
        store.close()


async def test_my_names_list_says_add_another_too(user: User):
    config.save_setup_state("done")
    await user.open("/")
    user.find(marker="nav-settings").click()
    (field,) = user.find(marker="add-me").elements
    assert field.props["placeholder"] == "Your BattleTag, e.g. Marv#2718"
    user.find(marker="add-me-button").trigger("click", "Marv#2718")
    await user.should_see(marker="remove-Marv#2718")
    (field,) = user.find(marker="add-me").elements
    assert field.props["placeholder"] == "Another name you play as…"
    assert config.identity().me == ("Marv#2718",)

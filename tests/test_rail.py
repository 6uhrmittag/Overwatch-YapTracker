"""The rail icon of the tab you're on (#404, Marv's rule): on the tab's main view it does
nothing, from a sub-page it goes back to the main view without the pop-in; other tabs as before."""

import time

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.store.repo import Store
from yaptracker.ui import shell

NOW = time.time()


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


@pytest.fixture
def store(tmp_path, monkeypatch):
    config.save_setup_state("done")
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    session = s.start_session(NOW - 600)
    match = s.start_match(session, NOW - 600, "heroselect", "UNRANKED", "ESPERANCA")
    pid = s.add_player("NoodleBonk", NOW - 500)
    s.add_message(ts=NOW - 500, channel="match", text="gg", match_id=match,
                  speaker_raw="NoodleBonk", player_id=pid)  # fmt: skip
    monkeypatch.setattr(runtime, "store", s)
    yield s
    s.close()


def calm(user: User) -> bool:
    """The content area has the no-pop-in class: what the rail sets when it goes back."""
    client = user.client
    main_area = next(e for e in client.elements.values() if "yt-main" in e.classes)
    return "yt-calm" in main_area.classes


async def test_the_main_view_stays_as_it_is(user: User, store):
    await user.open("/")
    user.find(marker="nav-yappers").click()
    user.find(marker="yapper-search").type("noodle")
    (box,) = user.find(marker="yapper-search").elements
    user.find(marker="nav-yappers").click()  # again
    assert user.find(marker="yapper-search").elements == {box} and box.value == "noodle"
    user.find(marker="nav-live").click()
    (feed,) = user.find(marker="callout-toggle").elements
    user.find(marker="nav-live").click()  # Live never reloads or clears
    assert user.find(marker="callout-toggle").elements == {feed}


async def test_from_a_sub_page_back_to_the_main_view_without_the_pop_in(user: User, store):
    await user.open("/")
    user.find(marker="nav-yappers").click()
    user.find(marker="yapper-1").click()
    await user.should_see(marker="back-to-yappers")
    user.find(marker="nav-yappers").click()
    await user.should_see(marker="yapper-list")
    await user.should_not_see(marker="back-to-yappers")
    assert calm(user)
    user.find(marker="nav-sessions").click()  # another tab: as always, with the pop-in
    assert not calm(user)
    session = store.sessions()[0].id
    user.find(marker=f"session-{session}").click()
    user.find(marker=f"match-{store.session_matches(session)[0].id}").click()
    await user.should_see(marker="transcript")
    user.find(marker="nav-sessions").click()
    await user.should_see(marker="sessions")
    assert calm(user)
    user.find(marker="nav-settings").click()
    user.find(marker="run-setup").click()
    await user.should_not_see(marker="chat-box")
    user.find(marker="nav-settings").click()
    await user.should_see(marker="chat-box")

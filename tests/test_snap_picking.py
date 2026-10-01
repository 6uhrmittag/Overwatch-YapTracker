"""Yap snaps (#155): pick lines in search too, shift-click a stretch, copy the PNG."""

import time
from types import SimpleNamespace

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.snaps import snap_lines
from yaptracker.store.repo import Store
from yaptracker.ui import shell


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    monkeypatch.setattr(runtime, "store", s)
    yield s
    s.close()


def evening(store):
    now = time.time()
    session = store.start_session(now - 900)
    match = store.start_match(session, now - 900, "heroselect", "UNRANKED", "OASIS")
    said = ["gl hf", "rein pls", "nice rein", "gg", "rein diff"]
    ids = [store.add_message(ts=now - 800 + n, channel="match", text=text, speaker_raw="Pickle",
                             match_id=match) for n, text in enumerate(said)]  # fmt: skip
    return session, match, ids


def test_lines_from_several_matches_get_clock_times():
    line = SimpleNamespace(channel="match", speaker_raw="Pickle", text="gg", role=None,
                           ts=time.mktime((2026, 10, 1, 20, 41, 5, 0, 0, -1)))  # fmt: skip
    assert snap_lines([line], started_at=None)[0].time == "20:41"
    assert snap_lines([line], started_at=line.ts - 65)[0].time == "1:05"


async def test_shift_click_picks_a_whole_stretch(user: User, store):
    config.save_setup_state("done")
    session, match, ids = evening(store)
    await user.open("/")
    user.find(marker="nav-sessions").click()
    user.find(marker=f"session-{session}").click()
    user.find(marker=f"match-{match}").click()
    user.find(marker="snap-start").click()
    user.find(marker=f"line-{ids[0]}").click()
    user.find(marker=f"line-{ids[3]}").trigger("click", {"shiftKey": True})
    await user.should_see("4 of 20 picked")
    user.find(marker=f"line-{ids[1]}").click()  # one out again
    await user.should_see("3 of 20 picked")


async def test_pick_in_search_results_and_copy(user: User, store):
    config.save_setup_state("done")
    _, _, ids = evening(store)
    await user.open("/")
    user.find(marker="nav-search").click()
    user.find(marker="search-box").type("rein")
    await user.should_see("3 yaps")
    user.find(marker="snap-start").click()
    user.find(marker=f"hit-{ids[4]}").click()  # newest first: "rein diff" is on top
    user.find(marker=f"hit-{ids[1]}").trigger("click", {"shiftKey": True})
    await user.should_see("3 of 20 picked")
    user.find(marker="snap-make").click()
    await user.should_see(marker="snap-preview")
    user.find(marker="snap-copy").trigger("click", "ok")  # what the browser reports back
    await user.should_see("Copied: paste it into Discord or WhatsApp.")
    user.find(marker="snap-copy").trigger("click", "no")
    await user.should_see("Couldn't copy here, but Save PNG works.")

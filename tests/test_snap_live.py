"""Yap snaps straight from Live (#325): the same picker as Sessions, and "Snap these" for lines
selected with the mouse."""

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.store.repo import Store
from yaptracker.ui import shell, views


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


@pytest.fixture
def live(tmp_path, monkeypatch):
    """A running match on Busan with three lines."""
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive()
    tracker.new_match(source="heroselect", mode="COMPETITIVE", map_name="BUSAN")
    ids = [store.add_message(ts=tracker.match_started_at + n, channel="match", text=text,
                             speaker_raw="Pickle", match_id=tracker.match_id)
           for n, text in enumerate(["gl hf", "tracer come here", "gg"])]  # fmt: skip
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "matches", tracker)
    config.save_setup_state("done")
    yield ids
    store.close()


async def test_make_a_yap_snap_in_live_with_the_picker(user: User, live, monkeypatch):
    made = []
    monkeypatch.setattr(views, "snap_dialog", lambda lines, footer, started: made.append(
        ([m.text for m in lines], footer)))  # fmt: skip
    await user.open("/")
    await user.should_see("tracer come here")
    user.find(marker="snap-start").click()
    user.find(marker=f"line-{live[0]}").click()
    user.find(marker=f"line-{live[2]}").trigger("click", {"shiftKey": True})
    await user.should_see("3 of 20 picked")
    user.find(marker="snap-make").click()
    ((lines, footer),) = made
    assert lines == ["gl hf", "tracer come here", "gg"]
    assert footer.startswith("Match 1 on Busan \u00b7 Competitive \u00b7 ")


async def test_lines_selected_with_the_mouse_offer_snap_these(user: User, live):
    await user.open("/")
    await user.should_see("tracer come here")
    button = user.find(marker="snap-these").elements.pop()
    assert "yt-hidden" in button.classes
    dom = [f"c{user.find(marker=f'line-{i}').elements.pop().id}" for i in live[:2]]
    feed = user.find(marker="feed")
    feed.trigger("ytselected", {"detail": dom[:1]})
    assert "yt-hidden" in button.classes  # one line: copy it, no snap
    feed.trigger("ytselected", {"detail": dom})
    assert "yt-hidden" not in button.classes
    user.find(marker="snap-these").click()
    await user.should_see("Your yap snap")


async def test_sessions_says_how_to_get_to_snaps(user: User, live):
    await user.open("/")
    user.find(marker="nav-sessions").click()
    user.find(marker=f"session-{runtime.matches.session_id}").click()
    await user.should_see("Open a match to read it back or make a yap snap.")

"""Heart a match to find it again (#282): stored, in the export, in Live and in Sessions."""

import json

import pytest
from nicegui.testing import User, user_simulation

from tests.test_sessions import evening
from yaptracker import config, runtime
from yaptracker.capture.watcher import CaptureWatcher
from yaptracker.export import export_all
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.store.repo import Store
from yaptracker.ui import shell


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


def test_a_heart_is_stored_shown_with_the_match_and_exported(store, tmp_path):
    session, first, second = evening(store)
    store.set_loved(first, 1_800_000_000.0)
    assert store.loved(first) and not store.loved(second)
    assert [m.loved_at for m in store.session_matches(session)] == [1_800_000_000.0, None]
    path = export_all(store, tmp_path / "out", 1_800_000_100.0, markdown=True)
    data = json.loads(path.read_text(encoding="utf-8"))
    loved = [m["loved_at"] for s in data["sessions"] for m in s["matches"]]
    assert loved[0].startswith("2027-") and loved[1] is None
    (md,) = (tmp_path / "out" / "sessions").glob("*.md")
    assert "· Loved" in md.read_text(encoding="utf-8").split("## Match 2")[0]
    store.set_loved(first, None)
    assert not store.loved(first)


def hearts(user: User) -> list:
    return [h for h in user.find(marker="heart").elements if "yt-hidden" not in h.classes]


async def test_live_hearts_the_running_match_and_undo_takes_it_back(user: User, store, monkeypatch):
    config.save_setup_state("done")
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive()
    watcher = CaptureWatcher(lambda: None, lambda _: None)
    watcher.state = "capturing"
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "watcher", watcher)
    monkeypatch.setattr(runtime, "matches", tracker)
    await user.open("/")
    await user.should_see("Between matches")
    assert hearts(user) == []  # nothing to love yet
    tracker.new_match(source="heroselect", mode="UNRANKED", map_name="KING'S ROW")
    await user.should_see("In a match", retries=50)
    (heart,) = hearts(user)
    user.find(marker="heart").click()
    assert store.loved(tracker.match_id) and "is-on" in heart.classes
    await user.should_see("Loved: the match on King's Row")
    tracker.end_match(outcome="victory")  # the last match keeps its heart until the next one
    await user.should_see("Last match · Victory", retries=50)
    assert "is-on" in hearts(user)[0].classes
    user.find(marker="undo").click()
    assert not store.loved(tracker.match_id) and "is-on" not in heart.classes


async def test_sessions_show_the_heart_and_the_transcript_can_love_a_match(
    user: User, store, monkeypatch
):
    config.save_setup_state("done")
    session, first, second = evening(store)
    store.set_loved(first, 1_800_000_000.0)
    monkeypatch.setattr(runtime, "store", store)
    await user.open("/")
    user.find(marker="nav-sessions").click()
    user.find(marker=f"session-{session}").click()
    await user.should_see("Match 1 on Esperanca")
    assert len(user.find(marker="loved").elements) == 1  # only the loved match has one
    user.find(marker=f"match-{second}").click()
    await user.should_see("Match 2")
    user.find(marker="heart").click()
    assert store.loved(second)
    await user.should_see("Loved: Match 2")

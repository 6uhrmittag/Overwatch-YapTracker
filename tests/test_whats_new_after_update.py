"""What's new once after an update (#412): Update now saves the notes it has; a manual update
uses the releases the daily check cached, or fetches once; never mid-match."""

import json

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, paths, runtime
from yaptracker.ui import shell
from yaptracker.updates import after_update, candidates, notes_for, save_notes, save_releases


def release(tag, *bullets):
    body = "### What's new\n" + "".join(f"- {b}\n" for b in bullets)
    return {"tag_name": tag, "prerelease": True, "draft": False, "body": body}


RELEASES = [  # newest first, like GitHub
    release("v0.5.412", "Grímsvötn is now **recognized**.", "Behind the scenes: a test."),
    release(
        "v0.5.410", "A quiet chat no longer splits a match.", "Grímsvötn is now **recognized**."
    ),
    release("v0.5.405", "Old news."),
    release("v0.5.399", "Older news."),
]


def no_fetch():
    raise AssertionError("must not go online")


def test_update_now_notes_are_shown_once_at_the_new_versions_first_start(tmp_path):
    notes = tmp_path / "whats_new.json"
    save_notes(notes, "0.5.405", "v0.5.412", ["Grímsvötn is now recognized."])
    found = after_update("0.5.412", "0.5.405", notes, tmp_path / "releases.json", no_fetch)
    assert found == {"from": "0.5.405", "to": "0.5.412", "notes": ["Grímsvötn is now recognized."]}
    assert notes_for("0.5.412", notes)["notes"] == ["Grímsvötn is now recognized."]


def test_a_manual_update_uses_the_cached_releases_up_to_the_installed_one(tmp_path):
    cache = tmp_path / "releases.json"
    save_releases(cache, candidates([release("v0.5.420", "Too new."), *RELEASES], "0.5.399"))
    found = after_update("0.5.410", "0.5.399", tmp_path / "whats_new.json", cache, no_fetch)
    assert found["notes"] == ["A quiet chat no longer splits a match.",
                              "Grímsvötn is now **recognized**.", "Old news."]  # fmt: skip
    assert "Too new." not in found["notes"]  # only up to the version that runs


def test_no_cache_fetches_once_and_offline_says_so(tmp_path):
    calls = []

    def fetch():
        calls.append(1)
        return RELEASES

    found = after_update("0.5.412", "0.5.410", tmp_path / "whats_new.json",
                         tmp_path / "releases.json", fetch)  # fmt: skip
    assert calls == [1] and found["notes"][0] == "Grímsvötn is now **recognized**."
    assert json.loads((tmp_path / "releases.json").read_text())  # cached for next time

    def offline():
        raise OSError("no network")

    found = after_update("0.5.412", "0.5.410", tmp_path / "x.json", tmp_path / "none.json", offline)
    assert found == {"from": "0.5.410", "to": "0.5.412", "notes": None}


def test_nothing_on_the_same_version_a_downgrade_or_unknown(tmp_path):
    for installed, last in (("0.5.412", "0.5.412"), ("0.5.405", "0.5.412"), ("0.5.412", None)):
        assert after_update(installed, last, tmp_path / "a.json", tmp_path / "b.json",
                            no_fetch) is None  # fmt: skip


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_the_dialog_waits_for_the_match_then_shows_once(user: User, monkeypatch, tmp_path):
    from yaptracker.matches import MatchTracker
    from yaptracker.pause import Pause
    from yaptracker.store.repo import Store

    config.save_setup_state("done")
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive()
    tracker.new_match(source="heroselect", mode="UNRANKED", map_name="KING'S ROW")
    found = {"from": "0.5.405", "to": "0.5.412", "notes": ["Grímsvötn is now recognized."]}
    monkeypatch.setattr(runtime, "after_update", found)
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "matches", tracker)
    await user.open("/")
    await user.should_not_see(marker="after-update", retries=15)  # in a match: later
    tracker.end_match(outcome="victory")
    await user.should_see("Fresh paint! Here's what changed since v0.5.405.", retries=50)
    await user.should_see("Grímsvötn is now recognized.")
    assert config.last_run_version() == "0.5.412"
    user.find(marker="after-update-ok").click()
    await user.open("/")
    await user.should_not_see(marker="after-update", retries=15)  # once
    store.close()


async def test_about_shows_what_came_with_this_version_again(user: User, monkeypatch, tmp_path):
    from yaptracker.updates import UpdateCheck

    config.save_setup_state("done")
    save_notes(paths.data_dir() / "whats_new.json", "0.5.405", "0.5.412", ["Old map fixed."])
    monkeypatch.setattr(runtime, "updates", UpdateCheck("0.5.412", lambda: False))
    await user.open("/")
    user.find(marker="nav-settings").click()
    user.find(marker="update-this-version").click()
    await user.should_see("Old map fixed.")

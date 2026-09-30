"""The window: icon rail and view switching, via NiceGUI's simulated user (no browser)."""

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import __version__
from yaptracker.ui import shell


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_opens_on_live(user: User):
    await user.open("/")
    await user.should_see("Live")
    await user.should_see("Waiting for Overwatch. I'll be right here.")


@pytest.mark.parametrize(
    ("key", "text"),
    [
        ("yappers", "Yappers"),
        ("sessions", "Sessions"),
        ("search", "Search"),
        ("settings", "Settings"),
        ("live", "This match"),
    ],
)
async def test_rail_switches_views(user: User, key: str, text: str):
    await user.open("/")
    user.find(marker=f"nav-{key}").click()
    await user.should_see(text)
    assert "is-active" in user.find(marker=f"nav-{key}").elements.pop().classes


async def test_settings_shows_version(user: User):
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see(f"YapTracker {__version__}")


def test_rail_has_all_five_views():
    assert [v.label for v in shell.VIEWS] == ["Live", "Yappers", "Sessions", "Search", "Settings"]


async def test_calibration_saves_the_box_for_the_screenshots_resolution(user: User, monkeypatch):
    from yaptracker import config, demo

    monkeypatch.setattr(demo, "ENABLED", True)
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("Not calibrated yet", retries=5)
    user.find(marker="calibrate").click()
    await user.should_see("Show me the chat box")
    await user.should_see("615 × 395 px at 55, 510")
    user.find(marker="save").click()
    await user.should_see("Saved")
    await user.should_see("16:9 screens: drawn at 2560×1440, 615 × 395 px at 55, 510")
    assert "16:9" in config.saved_chat_boxes()


async def test_calibration_shows_what_ocr_reads(user: User, monkeypatch):
    from yaptracker import demo

    monkeypatch.setattr(demo, "ENABLED", True)
    await user.open("/")
    user.find(marker="nav-settings").click()
    user.find(marker="calibrate").click()
    await user.should_see("6 yaps", retries=300)  # OCR runs in the background; slow CI boxes
    await user.should_see("not the wahoo guy again", retries=5)
    await user.should_see("SirPeelsALot (Reinhardt):", retries=5)


async def test_me_and_my_crew_saves_names(user: User):
    from yaptracker import config

    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("Me & my crew")
    user.find(marker="add-crew").trigger("keydown.enter", "Void")
    await user.should_see("Saved")
    assert config.identity().crew == ("Void",)
    user.find(marker="remove-Void").click()
    await user.should_not_see(marker="remove-Void")
    assert config.identity().crew == ()


async def test_live_view_follows_the_capture(user: User, monkeypatch):
    import numpy as np

    from yaptracker import runtime
    from yaptracker.capture.source import Frame
    from yaptracker.capture.watcher import CaptureWatcher

    watcher = CaptureWatcher(lambda: None, lambda _: None)
    monkeypatch.setattr(runtime, "watcher", watcher)
    await user.open("/")
    await user.should_see("Waiting for Overwatch")
    watcher.state, watcher.frames = "capturing", 1
    watcher.last_frame = Frame(0.0, np.zeros((395, 615, 3), np.uint8))
    user.find(marker="nav-yappers").click()
    user.find(marker="nav-live").click()
    await user.should_see("Listening for yaps")
    await user.should_see("Chat box 615 \u00d7 395 px, 1 frames")


async def test_pause_button_pauses_and_says_so(user: User, monkeypatch):
    from yaptracker import runtime
    from yaptracker.pause import Pause

    monkeypatch.setattr(runtime, "pause", Pause())
    await user.open("/")
    user.find(marker="pause").click()
    await user.should_see("Paused")
    await user.should_see("Ears covered. Nothing is being saved.")
    await user.should_see("Resume")
    user.find(marker="pause").click()
    await user.should_see("Waiting for Overwatch")
    assert not runtime.pause.paused


async def test_start_with_windows_is_explained_outside_the_installed_app(user: User):
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("Start with Windows")
    await user.should_see("Only in the installed app (tools/update.ps1).")


async def test_live_hints_once_when_the_window_size_changes(user: User, monkeypatch):
    from yaptracker import config, runtime
    from yaptracker.capture.source import Region
    from yaptracker.capture.watcher import CaptureWatcher

    config.save_chat_region(2560, 1440, Region(55, 510, 615, 395))
    watcher = CaptureWatcher(lambda: None, lambda _: None)
    watcher.state = "capturing"
    monkeypatch.setattr(runtime, "watcher", watcher)
    monkeypatch.setattr(runtime, "window_size", (1920, 1080))
    await user.open("/")
    await user.should_see("Overwatch runs at 1920×1080 now.")
    user.find(marker="size-ok").click()
    assert not config.size_needs_check(1920, 1080)


async def test_settings_shows_what_is_stored(user: User, monkeypatch, tmp_path):
    from yaptracker import runtime
    from yaptracker.store.repo import Store

    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    store.add_message(ts=1.0, channel="match", text="gg")
    monkeypatch.setattr(runtime, "store", store)
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("1 yaps, 0 matches, 0 yappers")
    store.close()


async def test_live_header_shows_session_and_match(user: User, monkeypatch, tmp_path):
    from yaptracker import runtime
    from yaptracker.matches import MatchTracker
    from yaptracker.pause import Pause
    from yaptracker.store.repo import Store

    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive()
    monkeypatch.setattr(runtime, "matches", tracker)
    await user.open("/")
    await user.should_see("Session 1 · no match yet")
    user.find(marker="new-match").click()
    await user.should_see("Session 1 · Match 1 · 0:0")
    store.close()

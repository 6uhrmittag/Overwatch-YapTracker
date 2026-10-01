"""The window: icon rail and view switching, via NiceGUI's simulated user (no browser)."""

import asyncio

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import __version__
from yaptracker.ui import shell


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


@pytest.fixture(autouse=True)
def _set_up_already():
    """Most tests are about the views after setup; the wizard tests start fresh (#76)."""
    from yaptracker import config

    config.save_setup_state("done")


def first_start():
    from yaptracker import paths

    paths.config_file().unlink()


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
    store.start_match(store.start_session(1.0), 1.0, "gap")
    monkeypatch.setattr(runtime, "store", store)
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("1 yap, 1 match, 0 yappers")
    store.close()


def test_counts_read_like_a_person_wrote_them():
    from yaptracker.ui.views import count

    counts = [count(n, "match", "matches") for n in (0, 1, 2)]
    assert counts == ["0 matches", "1 match", "2 matches"]


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


async def test_live_says_loudly_when_nothing_is_recorded(user: User, monkeypatch, tmp_path):
    from yaptracker import runtime
    from yaptracker.capture.health import CaptureHealth
    from yaptracker.store.repo import Store

    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    health = CaptureHealth(store)
    health.lost("crash")
    monkeypatch.setattr(runtime, "health", health)
    await user.open("/")
    await user.should_see("(capture stopped), trying again")
    await user.should_see("Not recording")
    await user.should_see("Overwatch is running, but I can't see it right now.")
    store.close()


async def test_open_logs_is_greyed_out_off_windows(user: User):
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see(marker="open-logs")
    button = next(iter(user.find(marker="open-logs").elements))
    assert "disabled" in button.props


async def test_open_logs_opens_the_folder_on_windows(user: User, monkeypatch):
    from yaptracker import logs

    opened = []
    monkeypatch.setattr(logs, "folder_opens", lambda: True)
    monkeypatch.setattr(logs, "open_folder", lambda: opened.append(True))
    await user.open("/")
    user.find(marker="nav-settings").click()
    button = next(iter(user.find(marker="open-logs").elements))
    assert "disabled" not in button.props
    user.find(marker="open-logs").click()
    assert opened == [True]


async def test_settings_shows_debug_samples_and_their_size(user: User, monkeypatch, tmp_path):
    from yaptracker import config, runtime
    from yaptracker.debug import DebugSamples

    (tmp_path / "debug" / "2026-10-01" / "12-00-00-end").mkdir(parents=True)
    (tmp_path / "debug" / "2026-10-01" / "12-00-00-end" / "a.jpg").write_bytes(b"x" * 2_500_000)
    monkeypatch.setattr(runtime, "debug", DebugSamples(tmp_path / "debug", config.debug_samples))
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("Debug samples: 2.5 MB, kept 14 days and 1 GB at most")
    assert config.debug_samples()  # on in pre-releases
    user.find(marker="debug-switch").click()
    assert not config.debug_samples()


async def test_first_start_walks_through_setup_and_ends_on_live(user: User, monkeypatch):
    from yaptracker import config, demo

    monkeypatch.setattr(demo, "ENABLED", True)  # the demo screenshot stands in for the game
    first_start()
    await user.open("/")
    await user.should_see("Let's find Overwatch")
    await user.should_see("Start Overwatch, I'll wait right here.")
    user.find(marker="setup-next").click()
    await user.should_see("Show me the chat box")  # step 2: the calibration from #10
    user.find(marker="save").click()  # the demo screenshot and the usual box: one click
    await user.should_see("Who are you?")
    await user.should_see("Me & my crew")
    await user.should_see("Start with Windows")
    user.find(marker="setup-done").click()
    await user.should_see("This match")
    assert config.setup_state() == "done"


async def test_skipping_setup_reminds_once(user: User):
    from yaptracker import config

    first_start()
    await user.open("/")
    user.find(marker="skip-setup").click()
    await user.should_see("Setup skipped: I'm using the usual chat spot")
    user.find(marker="setup-ok").click()
    assert config.setup_state() == "skipped-seen"
    await user.open("/")
    await user.should_see("This match")
    await user.should_not_see("Setup skipped")


async def test_setup_can_run_again_from_settings(user: User):
    await user.open("/")
    user.find(marker="nav-settings").click()
    user.find(marker="run-setup").click()
    await user.should_see("Let's find Overwatch")
    user.find(marker="skip-setup").click()
    await user.should_see("Settings")


def test_installs_from_before_the_wizard_count_as_set_up(tmp_path):
    from yaptracker import config
    from yaptracker.capture.source import Region

    path = tmp_path / "config.json"
    assert config.setup_state(path) is None
    config.save_chat_region(2560, 1440, Region(55, 510, 615, 395), path)
    assert config.setup_state(path) == "done"


async def test_calibrate_takes_the_screenshot_from_the_running_game(user: User, monkeypatch):
    import numpy as np

    from yaptracker import demo, runtime
    from yaptracker.capture.watcher import CaptureWatcher

    game = np.ascontiguousarray(np.asarray(demo.screenshot())[:, :, ::-1])
    taken = []
    watcher = CaptureWatcher(lambda: None, lambda _: None)
    watcher.state = "capturing"
    monkeypatch.setattr(watcher, "snapshot", lambda timeout=2.0: taken.append(1) or game)
    monkeypatch.setattr(runtime, "watcher", watcher)
    await user.open("/")
    user.find(marker="nav-settings").click()
    user.find(marker="calibrate").click()
    await user.should_see("This is Overwatch right now.")
    await user.should_see("615 × 395 px at 55, 510")  # the usual box, pre-filled
    user.find(marker="take-new").click()
    await user.should_see(marker="use-file")
    for _ in range(50):
        if len(taken) == 2:
            break
        await asyncio.sleep(0.05)
    assert len(taken) == 2


async def test_live_streams_the_chat_of_this_match(user: User, monkeypatch, tmp_path):
    from yaptracker import runtime
    from yaptracker.matches import MatchTracker
    from yaptracker.pause import Pause
    from yaptracker.store.repo import Store

    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive()
    tracker.chat_changed()
    start, match = tracker.match_started_at, tracker.match_id
    store.add_message(ts=start + 5, channel="match", speaker_raw="NoodleBonk", text="WAHOOOO",
                      match_id=match)  # fmt: skip
    store.add_message(ts=start + 65, channel="team", speaker_raw="tortillaTank", text="o/",
                      match_id=match, role="me")  # fmt: skip
    glitch = store.add_message(ts=start + 70, channel="system", speaker_raw="gremlin.exe",
                               text="[gremlin.exe] started playing Overwatch. EM",
                               match_id=match)  # fmt: skip
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "matches", tracker)
    await user.open("/")
    await user.should_see("WAHOOOO")
    await user.should_see("NoodleBonk:")
    await user.should_see("you:")  # own lines (#74)
    await user.should_see("1:05")  # time in the match
    await user.should_see("3 yaps · 2 yappers")
    store.update_message(glitch, channel="system", speaker_raw="gremlin.exe",
                         text="[gremlin.exe] started playing Overwatch.")  # fmt: skip
    await user.should_not_see("Overwatch. EM", retries=50)  # the better reading replaced it
    await user.should_see("[gremlin.exe] started playing Overwatch.")
    tracker.new_match()  # the next match starts with an empty feed
    await user.should_see("0 yaps · 0 yappers", retries=50)
    await user.should_not_see("WAHOOOO")
    store.close()


async def test_settings_shows_the_last_daily_backup(user: User):
    from yaptracker import paths

    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("No daily backup yet")
    paths.backup_dir().mkdir(parents=True, exist_ok=True)
    (paths.backup_dir() / "yaptracker-2026-10-01.db").write_bytes(b"x")  # written just now
    user.find(marker="nav-live").click()
    user.find(marker="nav-settings").click()
    await user.should_see("Last backup: today")
    await user.should_see("· 1 kept")


async def test_an_icon_shows_as_a_chip_and_the_line_opens_its_picture(user: User, monkeypatch,
                                                                       tmp_path):  # fmt: skip
    import numpy as np

    from yaptracker import runtime
    from yaptracker.capture.source import Region
    from yaptracker.lines import LinePictures
    from yaptracker.matches import MatchTracker
    from yaptracker.pause import Pause
    from yaptracker.store.repo import Store

    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive()
    tracker.chat_changed()
    pictures = LinePictures(tmp_path / "lines")
    ts = tracker.match_started_at + 3
    message = store.add_message(ts=ts, channel="team", speaker_raw="NoodleBonk",
                                text="Thanks! ◇", match_id=tracker.match_id,
                                has_glyphs=True)  # fmt: skip
    pictures.save(message, ts, np.full((80, 615, 3), 90, np.uint8), Region(14, 28, 200, 24))
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "matches", tracker)
    monkeypatch.setattr(runtime, "pictures", pictures)
    await user.open("/")
    await user.should_see("Thanks!")
    await user.should_see('class="yt-glyph"')  # the ◇ is a chip, not a bare character
    user.find(marker="chat-line").click()  # in the browser, a click on the text bubbles up
    await user.should_see(marker="line-picture")
    store.close()

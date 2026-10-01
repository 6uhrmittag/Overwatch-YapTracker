"""Settings -> Hotkeys (#32): change a hotkey by pressing it; clashes are shown, never saved."""

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.hotkeys import check
from yaptracker.ui import shell
from yaptracker.ui.hotkeys import clash, combo_from


def test_defaults_and_a_changed_one_persists():
    assert config.hotkeys() == {"pause": "Ctrl+Alt+P", "new_match": "Ctrl+Alt+M",
                                "lookup": "Ctrl+Alt+F", "save": "Ctrl+Alt+S"}  # fmt: skip
    config.save_hotkey("pause", "Ctrl+Shift+F8")
    assert config.hotkeys()["pause"] == "Ctrl+Shift+F8"
    assert config.hotkeys()["lookup"] == "Ctrl+Alt+F"


def test_key_presses_become_combos_by_key_position():
    assert combo_from("KeyP", ctrl=True, alt=True, shift=False) == "Ctrl+Alt+P"
    assert combo_from("Digit7", ctrl=True, alt=False, shift=True) == "Ctrl+Shift+7"
    assert combo_from("F9", ctrl=False, alt=False, shift=False) == "F9"
    assert combo_from("ControlLeft", ctrl=True, alt=False, shift=False) is None  # not done yet
    assert combo_from("Semicolon", ctrl=True, alt=True, shift=False) is None


def test_what_cant_be_a_hotkey():
    assert check("Ctrl+Alt+P") is None
    assert check("F9") is None
    assert "Ctrl or Alt" in check("Shift+P")  # you couldn't type a capital P anymore
    assert "Ctrl or Alt" in check("P")
    assert clash("pause", "Ctrl+Alt+F") == "Already used for Who's that?."
    assert clash("pause", "Ctrl+Alt+P") is None  # its own combo


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


def press(user, code, ctrl=True, alt=True, shift=False):
    user.find(marker="hotkey-keys").trigger("key", {
        "action": "keydown", "repeat": False, "key": code, "code": code, "location": 0,
        "altKey": alt, "ctrlKey": ctrl, "metaKey": False, "shiftKey": shift,
    })  # fmt: skip


async def test_change_a_hotkey_in_settings(user: User, monkeypatch):
    config.save_setup_state("done")
    bound = []
    monkeypatch.setattr(runtime, "bind_hotkeys", bound.append)
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("Hotkeys")
    user.find(marker="hotkey-change-pause").click()
    await user.should_see("Press the new keys…")
    assert bound == [False]  # YapTracker's own hotkeys rest while it listens
    press(user, "ControlLeft", alt=False)  # just a modifier: still listening
    await user.should_see("Press the new keys…")
    press(user, "KeyF")  # Ctrl+Alt+F is Who's that?
    await user.should_see("Ctrl Alt F: Already used for Who's that?.")
    assert config.hotkeys()["pause"] == "Ctrl+Alt+P" and bound == [False, True]
    user.find(marker="hotkey-change-pause").click()
    press(user, "KeyQ")
    await user.should_see("That's also AltGr+Q on German keyboards: no @ in chat.")
    assert config.hotkeys()["pause"] == "Ctrl+Alt+Q"  # allowed, with a heads-up
    user.find(marker="hotkey-change-pause").click()
    press(user, "Escape", ctrl=False, alt=False)
    await user.should_see("Ctrl Alt Q")
    user.find(marker="nav-live").click()
    await user.should_see("Ctrl Alt Q")  # the Pause button's keycap follows


async def test_another_app_has_it(user: User, monkeypatch):
    config.save_setup_state("done")

    class Taken:
        failed = ["Ctrl+Alt+S"]

    monkeypatch.setattr(runtime, "hotkeys", Taken())
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("Another app already has this one: pick another.")


async def test_leaving_settings_mid_listen_brings_the_hotkeys_back(user: User, monkeypatch):
    config.save_setup_state("done")
    bound = []
    monkeypatch.setattr(runtime, "bind_hotkeys", bound.append)
    await user.open("/")
    user.find(marker="nav-settings").click()
    user.find(marker="hotkey-change-save").click()
    user.find(marker="nav-live").click()
    await user.should_see("Pause")
    assert bound == [False, True]

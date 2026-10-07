"""Settings -> Hotkeys (#32): change a hotkey by pressing it; clashes are shown, never saved."""

import json

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, hotkeys, paths, runtime
from yaptracker.hotkeys import check
from yaptracker.ui import shell
from yaptracker.ui.hotkeys import clash, combo_from


def test_none_set_by_default_and_a_set_one_persists():
    assert config.hotkeys() == {"pause": "", "new_match": "", "lookup": "", "save": ""}  # (#328)
    config.save_hotkey("pause", "Ctrl+Shift+F8")
    assert config.hotkeys()["pause"] == "Ctrl+Shift+F8"
    assert config.hotkeys()["lookup"] == ""


def test_a_combo_saved_before_the_update_still_works():
    """Only changed combos were ever saved: Void's Dvorak one stays, the rest is unbound."""
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text(json.dumps({"hotkeys": {"pause": "Ctrl+Alt+N"}}))
    assert config.hotkeys() == {"pause": "Ctrl+Alt+N", "new_match": "", "lookup": "", "save": ""}
    assert runtime.keycap("pause") == "Ctrl Alt N" and runtime.keycap("lookup") == ""


def test_an_empty_combo_never_reaches_parse(monkeypatch):
    seen = []
    monkeypatch.setattr(hotkeys, "parse", lambda combo: seen.append(combo) or (0, 0))
    listener = hotkeys.HotkeyListener({"": lambda: None, "Ctrl+Alt+N": lambda: None})
    assert [combo for combo, _ in listener._bindings] == ["Ctrl+Alt+N"]
    assert clash("pause", "Ctrl+Alt+P") is None  # unbound actions don't clash with anything


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
    config.save_hotkey("lookup", "Ctrl+Alt+F")
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
    config.save_hotkey("lookup", "Ctrl+Alt+F")
    config.save_hotkey("pause", "Ctrl+Alt+P")
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


async def test_not_set_by_default_and_clear_unbinds_at_once(user: User, monkeypatch):
    config.save_setup_state("done")
    bound = []
    monkeypatch.setattr(runtime, "bind_hotkeys", bound.append)
    await user.open("/")
    await user.should_not_see("Ctrl Alt")  # no keycap chips in Live (#328)
    user.find(marker="nav-settings").click()
    await user.should_see("Optional. Everything works without hotkeys")
    for action in ("pause", "new_match", "lookup", "save"):
        user.find(marker=f"hotkey-unset-{action}")  # "Not set"
    await user.should_not_see("Clear")
    user.find(marker="hotkey-change-save").click()
    press(user, "KeyN")
    await user.should_see("Ctrl Alt N")
    user.find(marker="hotkey-clear-save").click()
    assert config.hotkeys()["save"] == "" and bound[-1] is True  # registered again, without it
    user.find(marker="hotkey-unset-save")
    await user.should_not_see("Ctrl Alt N")


async def test_another_app_has_it(user: User, monkeypatch):
    config.save_setup_state("done")

    class Taken:
        failed = ["Ctrl+Alt+S"]

    config.save_hotkey("save", "Ctrl+Alt+S")
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


# What some keys type, by where they sit (the browser's layout map), on three layouts (#245).
DVORAK = {"KeyL": "n", "KeyN": "b", "KeyF": "u", "KeyY": "f", "KeyR": "p", "KeyP": "l",
          "KeyQ": "'", "Digit7": "7"}  # fmt: skip
QWERTZ = {"KeyY": "z", "KeyZ": "y", "KeyP": "p", "KeyQ": "q", "Digit7": "7",
          "BracketLeft": "ü", "Semicolon": "ö", "Minus": "ß"}  # fmt: skip
QWERTY = {"KeyL": "l", "KeyP": "p", "KeyZ": "z", "Digit7": "7"}


def key_typing(layout: dict[str, str], letter: str) -> str:
    """Where the key that types `letter` sits: Windows fires VK_<letter> on that key."""
    return next(code for code, typed in layout.items() if typed == letter)


@pytest.mark.parametrize(("layout", "code", "letter"), [
    (DVORAK, "KeyL", "N"), (DVORAK, "KeyY", "F"), (DVORAK, "Digit7", "7"),
    (QWERTZ, "KeyY", "Z"), (QWERTZ, "KeyZ", "Y"), (QWERTZ, "KeyP", "P"),
    (QWERTY, "KeyL", "L"), (QWERTY, "KeyZ", "Z"),
])  # fmt: skip
def test_what_you_press_is_what_is_saved_shown_and_fired(layout, code, letter):
    from yaptracker.hotkeys import parse

    combo = combo_from(code, ctrl=True, alt=True, shift=False, layout=layout)
    assert combo == f"Ctrl+Alt+{letter}"  # saved, and shown as "Ctrl Alt N"
    _, vk = parse(combo)
    assert key_typing(layout, chr(vk).lower()) == code  # and it fires on the key you pressed


def test_umlauts_are_refused_and_other_keys_still_work():
    with pytest.raises(ValueError, match="can't be hotkeys"):
        combo_from("BracketLeft", ctrl=True, alt=True, shift=False, layout=QWERTZ)
    assert combo_from("F9", ctrl=False, alt=False, shift=False, layout=DVORAK) == "F9"
    assert combo_from("KeyQ", ctrl=True, alt=True, shift=False, layout=DVORAK) is None  # an '
    assert combo_from("KeyP", ctrl=True, alt=True, shift=False) == "Ctrl+Alt+P"  # no map: QWERTY

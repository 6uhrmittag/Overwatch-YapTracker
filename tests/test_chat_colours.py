"""Chat colours (#401): Overwatch's defaults, changeable in Settings, applied without a restart,
a warning for hard-to-read colours, and yap snaps in the night look follow them."""

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import chat_colours, config
from yaptracker.snaps import PRESETS, Style, preset_of, remembered, with_preset
from yaptracker.ui import shell


def test_overwatch_defaults_with_system_grey_and_what_you_saved():
    assert chat_colours.current() == {"team": "#00c1ff", "match": "#fd8d00", "group": "#7ce38b",
                                      "system": "#8a93a6", "chat": "#9aa3b5"}  # fmt: skip
    chat_colours.save("system", "#FFFF00")  # Void's yellow, as Overwatch has it
    config.save_chat_colours({**config.chat_colours(), "team": "not a colour"})
    assert chat_colours.current()["system"] == "#ffff00"
    assert chat_colours.current()["team"] == "#00c1ff"  # junk falls back to the default
    assert chat_colours.reset() == chat_colours.DEFAULTS


def test_readable_on_the_dark_panel():
    assert round(chat_colours.contrast("#000000", "#ffffff")) == 21
    assert all(chat_colours.readable(c) for c in ("#00c1ff", "#fd8d00", "#ffff00", "#8a93a6"))
    assert not chat_colours.readable("#3a2a6a")  # a dark purple


def test_css_and_js_set_the_theme_variables():
    colours = {**chat_colours.DEFAULTS, "team": "#123456"}
    assert "--yt-team: #123456;" in chat_colours.css(colours)
    assert chat_colours.css(colours).startswith("html:root {")  # wins over theme.css
    assert "s.setProperty('--yt-team', '#123456');" in chat_colours.js(colours)


def test_snaps_in_the_night_look_follow_the_chat_colours():
    chat = {**chat_colours.DEFAULTS, "team": "#123456", "system": "#ffff00"}
    old_night = Style(team="#5cc3ff", match="#ffae4d")  # saved before #401
    style = remembered(old_night.to_dict(), chat)
    assert (style.team, style.match, style.system) == ("#123456", "#fd8d00", "#ffff00")
    assert preset_of(style, chat) == "night"
    assert with_preset(Style(), "night", chat).team == "#123456"
    light = with_preset(Style(), "light")  # presets with their own colours stay as they are
    assert remembered(light.to_dict(), chat).team == PRESETS["light"][1].team
    assert preset_of(Style()) == "night"


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_pick_a_colour_in_settings_saved_with_a_warning_and_reset(user: User):
    config.save_setup_state("done")
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("Match the colours you use in Overwatch, so lines look the same here.")
    await user.should_see("[Someone] started playing Overwatch.")  # the system line, grey
    (card,) = user.find(marker="chat-colours").elements
    warning = next(e for e in card.descendants() if "colour-warning-team" in e._markers)
    assert not warning.visible
    with user.client:
        for picker in user.find(marker="colour-team").elements:
            picker.value = "#3a2a6a"
    assert config.chat_colours()["team"] == "#3a2a6a"
    assert warning.visible  # hard to read, but never blocked
    user.find(marker="colours-reset").click()
    assert chat_colours.current() == chat_colours.DEFAULTS
    await user.open("/")  # the next page load uses the colours too
    user.find(marker="nav-settings").click()
    (picker,) = user.find(marker="colour-team").elements
    assert picker.value == "#00c1ff"

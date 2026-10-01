"""Yap snap styles (#65): presets, own colours, font, switches; remembered; saved as previewed."""

import time
from types import SimpleNamespace

import pytest
from nicegui.testing import User, user_simulation
from PIL import Image

from yaptracker import config, paths, runtime
from yaptracker.snaps import PRESETS, Style, _layout, preset_of, render, snap_lines, with_preset
from yaptracker.store.repo import Store
from yaptracker.ui import shell

CHAT = [
    SimpleNamespace(channel="match", speaker_raw="NoodleBonk", text="wahoo", role=None, ts=65.0)
]


def hex_rgb(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[i : i + 2], 16) for i in (1, 3, 5))


def test_presets_change_colours_only_and_are_recognised():
    style = Style(font="barlow", timestamps=True)
    light = with_preset(style, "light")
    assert (light.font, light.timestamps) == ("barlow", True)
    assert light.background == PRESETS["light"][1].background
    assert preset_of(light) == "light" and preset_of(Style()) == "night"
    assert preset_of(Style(accent="#123456")) is None  # custom


def test_saved_style_survives_a_round_trip_and_ignores_junk():
    style = with_preset(Style(wordmark=False), "pastel")
    assert Style.from_dict(style.to_dict()) == style
    assert Style.from_dict({"accent": 5, "nope": 1, "rounded": False}) == Style(rounded=False)


def test_render_follows_the_style():
    lines = snap_lines(CHAT, hide_names=False, started_at=5.0)
    assert lines[0].time == "1:00"
    contrast = with_preset(Style(), "contrast")
    image = render(lines, "Match 1", contrast)
    assert image.getpixel((5, 5)) == hex_rgb(contrast.background)
    square = render(lines, "Match 1", Style(rounded=False))
    assert square.getpixel((48 + 2, 48 + 2)) == hex_rgb(Style().card)  # the card's corner
    bare = render(lines, "Match 1", Style(footer=False, wordmark=False))
    assert bare.height < render(lines, "Match 1").height
    texts = [op[3] for op in _layout(lines, 1000, Style(timestamps=True, channel_labels=False))[0]]
    assert "1:00" in texts and "MATCH" not in texts


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def open_snap(user, store, tmp_path):
    now = time.time()
    session = store.start_session(now - 600)
    match = store.start_match(session, now - 600, "heroselect", "push", "esperanca")
    line = store.add_message(ts=now - 500, channel="match", text="wahoo", speaker_raw="NoodleBonk",
                             match_id=match)  # fmt: skip
    await user.open("/")
    user.find(marker="nav-sessions").click()
    user.find(marker=f"session-{session}").click()
    user.find(marker=f"match-{match}").click()
    user.find(marker="snap-start").click()
    user.find(marker=f"line-{line}").click()
    user.find(marker="snap-make").click()
    await user.should_see(marker="snap-preview")


async def test_pick_a_preset_and_it_is_remembered_and_saved_as_shown(user: User, tmp_path,
                                                                       monkeypatch):  # fmt: skip
    config.save_setup_state("done")
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        monkeypatch.setattr(runtime, "store", store)
        monkeypatch.setattr(paths, "pictures_dir", lambda: tmp_path / "Pictures")
        await open_snap(user, store, tmp_path)
        user.find(marker="snap-preset-light").click()
        user.find(marker="snap-font-barlow").click()
        user.find(marker="snap-wordmark").click()  # off
        style = Style.from_dict(config.snap_style())
        assert (preset_of(style), style.font, style.wordmark) == ("light", "barlow", False)
        with user.client:
            for picker in user.find(marker="snap-colour-accent").elements:
                picker.value = "#ff00aa"
        await user.should_see("Custom")
        user.find(marker="snap-save").click()
        (saved,) = (tmp_path / "Pictures").glob("yapsnap-*.png")
        assert Image.open(saved).getpixel((5, 5)) == hex_rgb(PRESETS["light"][1].background)
    finally:
        store.close()

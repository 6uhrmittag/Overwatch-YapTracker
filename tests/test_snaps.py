"""Yap snaps (#64): picked lines -> a pretty PNG, names shown unless you hide them (#366)."""

import time
from types import SimpleNamespace

import pytest
from nicegui.testing import User, user_simulation
from PIL import Image

from yaptracker import config, paths, runtime
from yaptracker.glyphs import GLYPH
from yaptracker.snaps import SCALE, WIDTH, render, save, snap_lines
from yaptracker.store.repo import Store
from yaptracker.ui import shell, snap_dialog


def line(channel, who, text, role=None):
    return SimpleNamespace(channel=channel, speaker_raw=who, text=text, role=role)


CHAT = [
    line("system", "gremlin.exe", "[gremlin.exe] started playing Overwatch."),
    line("match", "NoodleBonk", "gl hf wahoo"),
    line("team", "tortillaTank", "ana pls, NoodleBonk is free", role="me"),
    line("team", "MoonPebble", "on it, tortillaTank " + GLYPH, role="crew"),
    line("match", "ana", "bananas"),
]


def test_hidden_names_are_numbered_by_first_appearance_also_in_the_text():
    shown = [(s.who, s.text) for s in snap_lines(CHAT, hide_names=True)]
    assert shown == [
        ("", "[Player 1] started playing Overwatch."),
        ("Player 2", "gl hf wahoo"),
        ("Me", "Player 4 pls, Player 2 is free"),  # "ana" spoke later, still hidden here
        ("Player 3", "on it, Me " + GLYPH),
        ("Player 4", "bananas"),  # whole names only: no "bPlayer 4nas"
    ]


def test_names_shown_or_me_and_crew_kept():
    assert [s.who for s in snap_lines(CHAT)] == [
        "", "NoodleBonk", "tortillaTank", "MoonPebble", "ana",
    ]  # fmt: skip
    kept = snap_lines(CHAT, hide_names=True, keep_crew=True)
    assert [s.who for s in kept] == ["", "Player 2", "tortillaTank", "MoonPebble", "Player 3"]
    assert kept[3].text == "on it, tortillaTank " + GLYPH


def test_render_is_twice_the_size_and_grows_with_long_lines():
    short = render(snap_lines(CHAT[:2]), "Match 2 on Esperança · Wed Sep 30, 2026")
    long = render(snap_lines([line("team", "zappy", "wahoo " * 60), line("match", "x", "Łódź")]))
    assert short.width == long.width == WIDTH * SCALE
    assert long.height > short.height
    assert short.getpixel((5, 5)) == (13, 16, 22)  # the night background


def test_saved_as_png_in_the_folder(tmp_path):
    path = save(render(snap_lines(CHAT)), tmp_path / "YapTracker", now=1_790_000_000)
    assert path.parent == tmp_path / "YapTracker" and path.name.startswith("yapsnap-")
    assert Image.open(path).format == "PNG"


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_pick_lines_preview_and_save(user: User, tmp_path, monkeypatch):
    config.save_setup_state("done")
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        now = time.time()
        session = store.start_session(now - 600)
        match = store.start_match(session, now - 600, "heroselect", "push", "esperanca")
        said = [("NoodleBonk", "gl hf"), ("zappy", "wahoo")]
        ids = [store.add_message(ts=now - 500 + n, channel="match", text=text, speaker_raw=who,
                                 match_id=match) for n, (who, text) in enumerate(said)]  # fmt: skip
        monkeypatch.setattr(runtime, "store", store)
        monkeypatch.setattr(paths, "pictures_dir", lambda: tmp_path / "Pictures" / "YapTracker")
        hidden = []  # Hide names per drawn snap (#366)

        def spy(messages, hide_names=False, *args, **kwargs):
            hidden.append(hide_names)
            return snap_lines(messages, hide_names, *args, **kwargs)

        monkeypatch.setattr(snap_dialog, "snap_lines", spy)
        await user.open("/")
        user.find(marker="nav-sessions").click()
        user.find(marker="day").click()
        user.find(marker=f"match-{match}").click()
        user.find(marker="snap-start").click()
        await user.should_see("0 of 20 picked")
        for message_id in ids:
            user.find(marker=f"line-{message_id}").click()
        await user.should_see("2 of 20 picked")
        user.find(marker=f"line-{ids[1]}").click()  # changed your mind
        await user.should_see("1 of 20 picked")
        user.find(marker=f"line-{ids[1]}").click()
        user.find(marker="snap-make").click()
        await user.should_see(marker="snap-preview")
        await user.should_see("hidden names become Player 1, 2, 3")
        assert hidden and not any(hidden)  # opens with names shown (#366)
        (crew,) = user.find(marker="snap-crew").elements
        assert "disabled" in crew.props  # only means something with Hide names (#397)
        user.find(marker="snap-hide").click()
        assert hidden[-1] is True  # and Hide names still hides them
        assert "disabled" not in crew.props
        user.find(marker="snap-save").click()
        await user.should_see("Saved to")
        assert list((tmp_path / "Pictures" / "YapTracker").glob("yapsnap-*.png"))
    finally:
        store.close()


async def test_twenty_lines_keep_the_buttons_in_view_and_a_full_png(user, tmp_path, monkeypatch):
    """#499: with ~18 lines Copy and Save were below the window; the dialog now scrolls in the
    middle, the buttons sit in a bar of their own, and only the on-screen preview shrinks."""
    config.save_setup_state("done")
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        now = time.time()
        session = store.start_session(now - 600)
        match = store.start_match(session, now - 600, "heroselect", "push", "esperanca")
        ids = [store.add_message(ts=now - 500 + n, channel="match", text=f"line {n} wahoo",
                                 speaker_raw="NoodleBonk", match_id=match)
               for n in range(20)]  # fmt: skip
        monkeypatch.setattr(runtime, "store", store)
        monkeypatch.setattr(paths, "pictures_dir", lambda: tmp_path / "Pictures")
        await user.open("/")
        user.find(marker="nav-sessions").click()
        user.find(marker="day").click()
        user.find(marker=f"match-{match}").click()
        user.find(marker="snap-start").click()
        for message_id in ids:
            user.find(marker=f"line-{message_id}").click()
        await user.should_see("20 of 20 picked")
        user.find(marker="snap-make").click()
        await user.should_see(marker="snap-preview")
        (scroll,) = user.find(marker="snap-scroll").elements
        (actions,) = user.find(marker="snap-actions").elements
        (save_button,) = user.find(marker="snap-save").elements
        inside = {id(e) for e in scroll.descendants()}
        assert id(actions) not in inside  # the buttons' bar never scrolls away
        assert id(save_button) in {id(e) for e in actions.descendants()}
        (preview,) = user.find(marker="snap-preview").elements
        user.find(marker="snap-preview").click()  # full size, inside the scrolling middle
        assert "yt-snap-preview--full" in preview.classes
        user.find(marker="snap-save").click()
        await user.should_see("Saved to")
        (saved,) = (tmp_path / "Pictures").glob("yapsnap-*.png")
        messages = [store.message(i) for i in ids]
        expected = render(snap_lines(messages, False, False, now - 600), "", config_style())
        assert Image.open(saved).size == expected.size  # the PNG itself never shrinks
    finally:
        store.close()


def config_style():
    from yaptracker import chat_colours
    from yaptracker.snaps import remembered

    return remembered(config.snap_style(), chat_colours.current())

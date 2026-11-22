"""Hero switches from chat's system lines (#262). The shapes are the ones in Marv's stored
chat, with made-up names."""

import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from nicegui.testing import User, user_simulation

from tests.test_channels import GREEN, frame
from yaptracker import channels, config, runtime
from yaptracker.capture.source import Region
from yaptracker.hero_switches import Switch, find, heroes, of_player, played
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import parse
from yaptracker.snaps import snap_lines
from yaptracker.store.repo import Store
from yaptracker.ui import shell

NOW = time.time()


@pytest.mark.parametrize(
    ("text", "name", "to", "was"),
    [
        ("MoonPebble switched to Vendetta (was Sierra).", "MoonPebble", "Vendetta", "Sierra"),
        # read into the yap above it, as every stored one is
        ("glhf <3 MoonPebble switched to Winston (was Roadhog).", "MoonPebble", "Winston",
         "Roadhog"),
        ("My ultimate is ready! ◇ Bo switched to Junker Queen (was Jetpack Cat)", "Bo",
         "Junker Queen", "Jetpack Cat"),
        # OCR: the icon as a mark, a misread hero, a cut-off end, a speck after the bracket
        ("Facts btw *tortillaTank switched to llari (was Zenyatta).", "tortillaTank", "Illari",
         "Zenyatta"),
        ("ouch * Bapricot switched to Doomfist (was D.V", "Bapricot", "Doomfist", "D.Va"),
        ("aaaah Bapricot switched to Ashe (was Pharahy).x", "Bapricot", "Ashe", "Pharah"),
    ],
)  # fmt: skip
def test_a_switch_is_found_at_the_end_of_a_line(text, name, to, was):
    assert find(text) == Switch(name, to, was)


@pytest.mark.parametrize("text", [
    "i switched to tank (was bored)",  # somebody talking: no heroes
    "he switched to Ana",
    "MoonPebble switched to Ana (was Mercy). and then some more",
    "gg wp",
])  # fmt: skip
def test_talk_about_switching_is_no_switch(text):
    assert find(text) is None


def test_one_players_history_by_name_whoever_the_line_belongs_to():
    rows = [
        (2, 900.0, "lol NoodleBonkl switched to Ashe (was Vendetta)"),  # an OCR slip of the name
        (1, 10.0, "NoodleBonk switched to Vendetta (was Sierra)."),
        (1, 11.0, "hi NoodleBonk switched to Vendetta (was Sierra)."),  # stored twice
        (1, 20.0, "gg Noodle switched to Mei (was Ana)."),  # somebody else
        (1, 25.0, "NoodleBonk switched to Mercy (was Ashe)."),  # the switch to Ashe wasn't read
        (1, 90.0, "NoodleBonk switched to Ashe (was Mercy)."),  # ... and back and forth
        (1, 150.0, "NoodleBonk switched to Mercy (was Ashe)."),
    ]
    switches = of_player(rows, ["NoodleBonk"])
    assert [(s.match_id, s.ts, s.to) for s in switches] == [
        (1, 10.0, "Vendetta"), (1, 25.0, "Mercy"), (1, 90.0, "Ashe"), (1, 150.0, "Mercy"),
        (2, 900.0, "Ashe")]  # fmt: skip
    assert played(switches) == {
        1: "Sierra → Vendetta → Ashe → Mercy → Ashe → Mercy",
        2: "Vendetta → Ashe"}  # fmt: skip
    assert heroes(switches) == ["Ashe", "Vendetta", "Mercy", "Sierra"]
    assert of_player(rows, ["tortillaTank"]) == []


def _line(text, y):
    return OcrLine(text, 0.99, Region(64, y, 400, 24))


def test_the_parser_keeps_a_switch_as_its_own_system_line():
    """It sits as close under a yap as a wrapped row and was joined to it. Talk that wraps
    ("i switched to ...") still is."""
    lines = [_line("[Bapricot]: honestly", 10), _line("i switched to tank (was bored)", 39),
             _line("MoonPebble switched to Ashe (was Sierra).", 68),
             _line("* MoonPebble switched to Mei (was Ashe). ◇", 97),
             _line("*MoonPebble switched to Ana (was Mei)", 126)]  # fmt: skip
    parsed = parse(lines)
    assert [(p.kind, p.channel, p.speaker, p.text) for p in parsed] == [
        ("message", "unknown", "Bapricot", "honestly i switched to tank (was bored)"),
        ("system", "system", "MoonPebble", "MoonPebble switched to Ashe (was Sierra)."),
        ("system", "system", "MoonPebble", "MoonPebble switched to Mei (was Ashe)."),
        ("system", "system", "MoonPebble", "MoonPebble switched to Ana (was Mei)"),
    ]
    # Overwatch draws it in the team's colour: it teaches nothing about the system colour
    image, boxes = frame([("MoonPebble switched to Ashe (was Sierra).", GREEN)])
    switch = replace(parsed[1], box=boxes[0], head=boxes[0])
    assert channels.learn([switch], image) == {}
    assert "system" in channels.learn([replace(switch, text="[Bo] left the game.")], image)


def test_a_snap_with_hidden_names_hides_the_switchers_name():
    line = SimpleNamespace(channel="system", speaker_raw="MoonPebble", role=None,
                           text="MoonPebble switched to Ashe (was Sierra).")  # fmt: skip
    assert snap_lines([line], hide_names=True)[0].text == "Player 1 switched to Ashe (was Sierra)."


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


@pytest.fixture
def store(tmp_path, monkeypatch):
    config.save_setup_state("done")
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    session = s.start_session(NOW - 7200)
    pid = s.add_player("NoodleBonk", NOW - 7200)
    other = s.add_player("Bapricot", NOW - 7200)
    match = s.start_match(session, NOW - 7200, "heroselect")
    s.add_message(ts=NOW - 7100, channel="match", text="WAHOOOO", match_id=match,
                  speaker_raw="NoodleBonk", player_id=pid)  # fmt: skip
    s.add_message(ts=NOW - 7000, channel="team", text="Group up!", match_id=match, hero="Lucio",
                  speaker_raw="NoodleBonk", player_id=pid)  # fmt: skip
    # an old line: the switch read into somebody else's yap
    s.add_message(ts=NOW - 6900, channel="team", match_id=match, player_id=other,
                  text="hi NoodleBonk switched to Vendetta (was Sierra).")  # fmt: skip
    # a new one: its own system line, nobody's
    s.add_message(ts=NOW - 6800, channel="system", match_id=match, speaker_raw="NoodleBonk",
                  text="NoodleBonk switched to Ashe (was Vendetta).")  # fmt: skip
    edited = s.add_message(ts=NOW - 6700, channel="team", match_id=match, player_id=other,
                           text="gg NoodleBonk switched to Mei (was Ashe)")  # fmt: skip
    s.edit_message(edited, "gg", NOW)  # tidied by hand: the switch is still known
    gone = s.add_message(ts=NOW - 6600, channel="system", match_id=match,
                         text="NoodleBonk switched to Ana (was Mei).")  # fmt: skip
    s.delete_message(gone, NOW)  # a deleted line says nothing
    monkeypatch.setattr(runtime, "store", s)
    yield s
    s.close()


async def test_the_profile_shows_what_they_played(user: User, store):
    await user.open("/")
    user.find(marker="nav-yappers").click()
    user.find(marker="yapper").click()  # the list's first: NoodleBonk
    await user.should_see("Seen as Lucio, Mei, Ashe, Vendetta, Sierra")  # callouts first
    await user.should_see("1 yap · Played Sierra → Vendetta → Ashe → Mei")
    assert store.player(1).callouts == 1  # a switch is no callout

"""Familiar faces (#26, #518): a chip for people you met before, once per match, never for me/crew;
it stays for the match and clears itself when the next one starts."""

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.familiar import FamiliarFaces
from yaptracker.identity import Identity
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.store.repo import Store
from yaptracker.ui import shell


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def met(store, name, matches, verdict=None, notes=""):
    """A player who said one line in each of `matches` earlier matches; returns (id, new match)."""
    session = store.start_session(1.0)
    pid = store.add_player(name, 1.0)
    for n in range(matches):
        match = store.start_match(session, 10.0 + n, "gap")
        store.add_message(ts=10.0 + n, channel="match", text="gg", match_id=match,
                          speaker_raw=name, player_id=pid)  # fmt: skip
    if verdict:
        store.set_verdict(pid, verdict)
    store.set_notes(pid, notes)
    return pid, store.start_match(session, 100.0, "heroselect")


def test_someone_you_met_before_gets_a_card_with_what_you_know(store):
    pid, now = met(store, "NoodleBonk", 3, "friend", "Hype Lucio. Greet with a wahoo.\nEU.")
    faces = FamiliarFaces(store, clock=Clock())
    card = faces.heard(pid, now)
    assert (card.name, card.verdict, card.matches, card.yaps) == ("NoodleBonk", "friend", 3, 3)
    assert card.note == "Hype Lucio. Greet with a wahoo."  # the first line only
    assert faces.active() == [card]


def test_first_time_met_no_card_and_only_once_per_match(store):
    new, now = met(store, "zappy", 0)
    old, _ = met(store, "mossyfox", 1)
    faces = FamiliarFaces(store, clock=Clock())
    assert faces.heard(new, now) is None  # never met before
    assert faces.heard(old, now) is not None
    assert faces.heard(old, now) is None  # their second line: no second card
    assert faces.heard(None, now) is None  # system line


def test_me_and_my_crew_never_get_a_card(store):
    crew, now = met(store, "MoonPebble", 5)
    faces = FamiliarFaces(store, lambda: Identity(crew=("MoonPebble",)), clock=Clock())
    assert faces.heard(crew, now) is None


def test_chips_stack_newest_first_stay_and_clear_at_the_next_match(store):
    a, now = met(store, "NoodleBonk", 1)
    b, _ = met(store, "gremlin.exe", 1, "avoid")
    clock = Clock()
    faces = FamiliarFaces(store, clock=clock)
    faces.heard(a, now)
    clock.now += 10
    faces.heard(b, now)
    assert [c.name for c in faces.active()] == ["gremlin.exe", "NoodleBonk"]
    clock.now += 3600  # no fading, no "Got it": they stay for the whole match
    assert len(faces.active()) == 2
    nxt = now + 1
    faces.heard(a, nxt)  # already heard in the next match before it was noticed: stays
    faces.match_started(nxt)
    assert [c.name for c in faces.active()] == ["NoodleBonk"]
    faces.match_started(nxt + 1)
    assert faces.active() == []


def test_a_new_match_clears_the_faces_by_itself(store):
    """The match tracker tells the faces, not the UI: works with the window in the background."""
    pid, now = met(store, "NoodleBonk", 2)
    faces = FamiliarFaces(store)
    tracker = MatchTracker(store, Pause(), on_match_start=faces.match_started)
    faces.heard(pid, now)
    tracker.new_match(2000.0, "heroselect", "UNRANKED")
    assert faces.active() == []


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


def popovers(user: User) -> list:
    return sorted(user.find(marker="face-pop").elements, key=lambda e: e.id)


async def test_a_chip_opens_the_full_card_and_that_their_profile(user: User, store, monkeypatch):
    config.save_setup_state("done")
    pid, now = met(store, "NoodleBonk", 3, "friend", "Hype Lucio.")
    faces = FamiliarFaces(store)
    faces.heard(pid, now)
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "familiar", faces)
    await user.open("/")
    await user.should_see("Look who's back!")
    await user.should_see(marker="face-chip")
    await user.should_see("“Hype Lucio.”")  # on the chip: the first words of the note
    assert [m.value for m in popovers(user)] == [False]  # the full card only on a click
    user.find(marker="face-chip").click()
    assert [m.value for m in popovers(user)] == [True]
    await user.should_see("3 matches together")
    user.find(marker="face-open").click()
    await user.should_see("Your verdict")  # the profile, from the card


async def test_quiet_when_empty_red_for_nope_plus_n_and_never_a_got_it(
    user: User, store, monkeypatch
):
    config.save_setup_state("done")
    faces = FamiliarFaces(store)
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "familiar", faces)
    await user.open("/")
    await user.should_see("Familiar faces show up here.")
    names = ["NoodleBonk", "gremlin.exe", "Pebble", "Kettle", "Mothball"]
    for n, name in enumerate(names):
        pid, now = met(store, name, 1, "avoid" if n == 4 else None)
        faces.heard(pid, now)
    await user.should_see(marker="face-avoid-chip")  # the newest, a Nope: red, same strip
    await user.should_see("+2")  # 3 chips, the rest behind "+2"
    assert len(user.find(marker="face-chip").elements) == 2
    await user.should_not_see("Familiar faces show up here.")
    await user.should_not_see(marker="face-ok")  # no "Got it" any more (#518)


def test_never_a_card_for_me_or_crew_under_any_spelling_also_added_later(store):
    """#168: the names were typed in after the players existed, and only an alias matches."""
    void, now = met(store, "MoonPebble", 3)  # read long before "Void" went into My crew
    store.add_alias(void, "Void")
    names = {"crew": ()}
    faces = FamiliarFaces(store, lambda: Identity(crew=names["crew"]), clock=Clock())
    names["crew"] = ("Void",)  # added in Settings now; FamiliarFaces reads it at every line
    assert faces.heard(void, now) is None


def test_each_card_is_one_log_line_with_the_player_id_only(store, caplog):
    """#437: the evening counts familiar faces from the log; never a name in it."""
    import logging
    import time

    pid, now = met(store, "NoodleBonk", 2)
    with caplog.at_level(logging.INFO, logger="yaptracker.familiar"):
        FamiliarFaces(store, clock=Clock()).heard(pid, now)
    met_on = time.strftime("%Y-%m-%d", time.localtime(11.0))
    assert caplog.messages == [f"familiar face: player #{pid} (last met {met_on})"]
    assert "NoodleBonk" not in caplog.text


def test_a_card_from_after_the_match_says_so_in_the_log(store, caplog):
    """#437: the evening tells live cards from ones read after the match."""
    import logging

    pid, now = met(store, "NoodleBonk", 2)
    with caplog.at_level(logging.INFO, logger="yaptracker.familiar"):
        FamiliarFaces(store, clock=Clock()).heard(pid, now, after=True)
    assert caplog.messages[0].endswith(", after the match")


def test_the_tidy_up_of_an_older_match_doesnt_card_a_player_twice(store):
    """#437: the tidy-up reads match 1 while match 2 runs; each match carded once per player."""
    pid, now = met(store, "NoodleBonk", 2)
    older = store.start_match(store.start_session(20.0), 20.0, "heroselect", None, None)
    faces = FamiliarFaces(store, clock=Clock())
    assert faces.heard(pid, now) is not None
    faces.heard(pid, older, after=True)  # the tidy-up, in between
    assert faces.heard(pid, now) is None
    assert faces.heard(pid, older, after=True) is None

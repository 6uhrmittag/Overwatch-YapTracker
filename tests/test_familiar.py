"""Familiar faces (#26): a card for people you met before, once per match, never for me/crew."""

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.familiar import SHOW_S, FamiliarFaces
from yaptracker.identity import Identity
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


def test_cards_stack_newest_first_and_fade(store):
    a, now = met(store, "NoodleBonk", 1)
    b, _ = met(store, "gremlin.exe", 1, "avoid")
    clock = Clock()
    faces = FamiliarFaces(store, clock=clock)
    faces.heard(a, now)
    clock.now += 10
    faces.heard(b, now)
    assert [c.name for c in faces.active()] == ["gremlin.exe", "NoodleBonk"]
    faces.dismiss(b)  # "Got it"
    assert [c.name for c in faces.active()] == ["NoodleBonk"]
    clock.now += SHOW_S
    assert faces.active() == []


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_live_shows_the_card_and_it_opens_their_profile(user: User, store, monkeypatch):
    config.save_setup_state("done")
    pid, now = met(store, "NoodleBonk", 3, "friend", "Hype Lucio.")
    faces = FamiliarFaces(store)
    faces.heard(pid, now)
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "familiar", faces)
    await user.open("/")
    await user.should_see("Look who's back!")
    await user.should_see("NoodleBonk")
    await user.should_see("3 matches together")
    await user.should_see("“Hype Lucio.”")
    user.find(marker="face-open").click()
    await user.should_see("Your verdict")  # the profile, from the card


async def test_got_it_and_the_compact_nope_card(user: User, store, monkeypatch):
    config.save_setup_state("done")
    friend, now = met(store, "NoodleBonk", 1, "friend")
    nope, _ = met(store, "gremlin.exe", 1, "avoid", "rage-quits in overtime")
    faces = FamiliarFaces(store)
    faces.heard(friend, now)
    faces.heard(nope, now)
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "familiar", faces)
    await user.open("/")
    await user.should_see(marker="face-avoid")
    await user.should_see("rage-quits in overtime")
    user.find(marker="face-ok").click()
    await user.should_not_see(marker="face-ok")
    await user.should_see(marker="face-avoid")


def test_never_a_card_for_me_or_crew_under_any_spelling_also_added_later(store):
    """#168: the names were typed in after the players existed, and only an alias matches."""
    void, now = met(store, "MoonPebble", 3)  # read long before "Void" went into My crew
    store.add_alias(void, "Void")
    names = {"crew": ()}
    faces = FamiliarFaces(store, lambda: Identity(crew=names["crew"]), clock=Clock())
    names["crew"] = ("Void",)  # added in Settings now; FamiliarFaces reads it at every line
    assert faces.heard(void, now) is None

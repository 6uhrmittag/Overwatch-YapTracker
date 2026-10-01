"""Speakers become players (#23): OCR slips stay one player, different people don't merge."""

import pytest

from yaptracker.identity import Identity
from yaptracker.players import PlayerMatcher
from yaptracker.store.repo import Store


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def players(store):
    return store._read("SELECT id, display_name FROM players ORDER BY id")


def aliases(store):
    return sorted(a for (a,) in store._read("SELECT alias FROM player_aliases"))


def test_ocr_slips_are_one_player_and_become_aliases(store):
    matcher = PlayerMatcher(store)
    ids = {matcher.link(name, 1.0) for name in ["NoodleBonk", "NoodleBonkl", "NoodIeBonk",
                                                 "NoodleBonk#2718"]}  # fmt: skip
    assert len(ids) == 1 and len(players(store)) == 1
    assert aliases(store) == ["NoodIeBonk", "NoodleBonkl"]


def test_different_people_stay_different(store):
    matcher = PlayerMatcher(store)
    names = ["mossyfox", "zappy", "Bo", "Bob", "MaybeMaybe", "SirPeelsALot"]
    assert len({matcher.link(name, 1.0) for name in names}) == len(names)


def test_real_misreads_from_the_recording(store):
    matcher = PlayerMatcher(store)
    for right, misread in [("VoidCrowned", "VoidGrowned"), ("IDontKnowMan", "IDoftKnowMan"),
                           ("uwultrararww", "uwultrararwwl")]:  # fmt: skip
        assert matcher.link(right, 1.0) == matcher.link(misread, 2.0)


def test_my_names_never_become_a_player_and_crew_does(store):
    me_and_crew = Identity(me=("tortillaTank",), crew=("NoodleBonk",))
    matcher = PlayerMatcher(store, lambda: me_and_crew)
    assert matcher.link("tortillaTank", 1.0) is None
    assert matcher.link("tortiIlaTank", 1.0) is None  # me, misread
    crew = matcher.link("NoodleBonk", 1.0)
    assert crew is not None and me_and_crew.role(players(store)[0][1]) == "crew"
    assert matcher.link(None, 1.0) is None  # "You endorsed …": no speaker


def test_the_name_shown_is_the_spelling_read_most_often(store):
    matcher = PlayerMatcher(store)
    pid = matcher.link("VoidGrowned", 1.0)  # the very first reading was a slip
    for t in (2.0, 3.0):
        matcher.link("VoidCrowned", t)
    assert players(store) == [(pid, "VoidCrowned")]
    assert store._read("SELECT first_seen, last_seen FROM players") == [(1.0, 3.0)]


def test_a_shaky_new_name_is_kept_as_a_debug_sample(store):
    shaky = []
    matcher = PlayerMatcher(store, on_shaky=shaky.append)
    matcher.link("NoodleBonk", 1.0)
    matcher.link("zappy", 1.0, confidence=0.6)  # new, but read badly
    matcher.link("NoodleBank", 1.0)  # new? close to a known name (ratio 90 → it's an alias)
    matcher.link("NoodleBoots", 1.0)  # new, but near a known name (76 %)
    assert shaky == ["zappy", "NoodleBoots"]


def test_players_are_found_again_after_a_restart(store):
    first = PlayerMatcher(store).link("mossyfox", 1.0)
    assert PlayerMatcher(store).link("mossyfoxl", 2.0) == first

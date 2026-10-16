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
    for right, misread in [("MoonPebble", "MoonPebbIe"), ("BlueTeaKettle", "BlueTeaKetlle"),
                           ("wobblewobble", "wobblewobblel")]:  # fmt: skip
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
    pid = matcher.link("MoonPebbIe", 1.0)  # the very first reading was a slip
    for t in (2.0, 3.0):
        matcher.link("MoonPebble", t)
    assert players(store) == [(pid, "MoonPebble")]
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


def test_a_player_removed_by_a_clean_up_is_made_again_not_reused(store):
    """#458: link() handed out the removed id, add_message failed with FOREIGN KEY."""
    players = PlayerMatcher(store)
    pid = players.link("Garbleguy", 1.0)
    line = store.add_message(ts=1.0, channel="match", text="hi", player_id=pid)
    assert store.remove_lines([line]) == 1  # a light misread: the tidy-up takes it and its player
    again = players.link("Garbleguy", 2.0)  # the matcher wasn't told
    store.add_message(ts=2.0, channel="match", text="hi again", player_id=again)  # stored
    assert [p.display_name for p in store.players()] == ["Garbleguy"]  # made again


def test_after_a_merge_the_name_links_to_the_player_it_went_to(store):
    players = PlayerMatcher(store)
    kept, merged = players.link("NoodleBonk", 1.0), players.link("Pickle", 1.0)
    before = players.generation
    store.merge_players(merged, kept)  # without reload(): another thread was faster
    assert players.link("Pickle", 2.0) == kept and players.generation > before


def test_a_better_reading_after_a_merge_gets_the_player_it_went_to(store):
    import numpy as np

    from yaptracker.capture.source import Region
    from yaptracker.matches import MatchTracker
    from yaptracker.ocr.engine import OcrLine
    from yaptracker.pause import Pause
    from yaptracker.reader import ChatReader

    players = PlayerMatcher(store)
    kept = players.link("NoodleBonk", 1.0)
    reads = iter([[OcrLine("[Pickle]: wahoo tean", 0.80, Region(64, 300, 300, 24))],
                  [OcrLine("[Pickle]: wahoo team", 0.99, Region(64, 300, 300, 24))]])  # fmt: skip
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(1000.0)
    reader = ChatReader(lambda _: next(reads), store, tracker, players=players)
    reader.read_frame(1000.0, np.zeros((395, 615, 3), np.uint8))
    (line,) = store.messages(tracker.match_id)
    store.merge_players(line.player_id, kept)  # "Pickle" is NoodleBonk's other name
    players.reload()
    reader.read_frame(1001.5, np.zeros((395, 615, 3), np.uint8))  # read better, still on screen
    (line,) = store.messages(tracker.match_id)
    assert line.text == "wahoo team" and line.player_id == kept

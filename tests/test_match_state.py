"""The match in words for Live (#268): in a match, match over, between matches."""

from yaptracker.matches import AFTER_END_GAP_S, Status
from yaptracker.ui.views import BETWEEN, match_state

T0 = 1_000_000.0


def test_before_the_first_match_it_is_between_matches():
    assert match_state(None, T0) == ("Between matches", BETWEEN)
    assert match_state(Status(1, None, None), T0) == ("Between matches", BETWEEN)


def test_in_a_match_with_map_mode_and_time():
    where = Status(1, 3, T0, "KING'S ROW", mode="UNRANKED")
    assert match_state(where, T0 + 252) == ("In a match", "King's Row · Unranked · 4:12")


def test_a_match_without_hero_select_still_says_how_long():
    assert match_state(Status(1, 3, T0), T0 + 65) == ("In a match", "Match 3 · 1:05")


def test_match_over_then_between_matches():
    where = Status(1, 3, T0, "KING'S ROW", True, "victory", "UNRANKED", T0 + 552)
    assert match_state(where, T0 + 560) == (
        "Match over",
        "Victory on King's Row · 9:12 · waiting for the next one",
    )
    assert match_state(where, T0 + 552 + AFTER_END_GAP_S) == ("Between matches", BETWEEN)


def test_an_end_without_outcome_says_over():
    where = Status(1, 3, T0, None, True, None, None, T0 + 60)
    assert match_state(where, T0 + 61) == ("Match over", "Over · 1:00 · waiting for the next one")

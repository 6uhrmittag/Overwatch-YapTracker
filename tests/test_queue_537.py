"""Queue unknown in half the matches after Overwatch's November patch (#537). The label didn't
change: glare hid the banner (the round-start backup started the match without the corner), or
washed the queue word into fragments. Replay of the 22 real start samples, 2026-11-09..14."""

import json
from pathlib import Path

import numpy as np
import pytest

from yaptracker import game_lists
from yaptracker.signals import parse_info, read_info

SAMPLES = json.loads((Path(__file__).parent / "fixtures" / "signals" / "queue-2026-11.json")
                     .read_text(encoding="utf-8"))["samples"]  # fmt: skip
CORNER = np.zeros((360, 1170, 3), np.uint8)


@pytest.mark.parametrize("sample", sorted(SAMPLES))
def test_every_start_sample_reads_its_queue_or_says_unknown_never_wrong(sample):
    expected = SAMPLES[sample]
    looks = iter(expected["looks"] + [[]] * 3)
    mode, map_name = read_info(lambda image: next(looks), CORNER)
    assert (mode, map_name) == (expected["queue"], expected["map"])
    assert mode in (None, "UNRANKED")  # every one of them was Unranked


def test_the_samples_read_more_queues_than_before():
    known = 0
    for sample in SAMPLES.values():
        looks = iter(sample["looks"] + [[]] * 3)
        known += read_info(lambda image, looks=looks: next(looks), CORNER)[0] is not None
    no_corner = sum(1 for s in SAMPLES.values() if "no corner" in s.get("unknown_because", ""))
    assert (known, no_corner) == (10, 6)  # 9 before; the 6 get the HERO DETAILS read instead


@pytest.mark.parametrize("read", ["IINRONKE", "INRONKE", "LINRONKE", "UNRANEES", "ANKED", "ONKED",
                                  "YANKED"])  # fmt: skip
def test_a_washed_out_unranked_still_counts(read):
    assert game_lists.loose_queue(read) == "UNRANKED"
    assert game_lists.queue(read) in (None, "UNRANKED")  # the strict look stays as it was


@pytest.mark.parametrize("read", ["ATTACK", "DEFEND", "DEYENI", "MTTACK", "ATACK", "SOCIAL",
                                  "NRHIN", "UNRO", "DANK", "VOTE FOR A MAP", "ROLE QUEUE",
                                  "GENERAL COMBAT INTERFACE", "ENABLE QUICK PRESS PRAISE",
                                  "ANGRIFF", "VERTEIDIGUNG", "PREPARE",
                                  "TLE PASS SHOP"])  # fmt: skip
def test_other_text_at_that_spot_stays_unknown(read):
    """Real reads at the corner (sides, menus, glare fragments): none of them is a queue."""
    assert game_lists.loose_queue(read) is None


@pytest.mark.parametrize("read", ["COMPETITVE", "MPETITIVE", "CNMPETITINE", "PETITIVE"])
def test_a_washed_out_competitive_never_turns_unranked(read):
    assert game_lists.loose_queue(read) == "COMPETITIVE"


def test_the_queue_is_found_below_the_side_too():
    """OCR's line order isn't fixed: the side can come first, the queue as part of a line."""
    assert parse_info(["ATTACK", "UNRANKED", "DORADO"]) == ("UNRANKED", "Dorado")
    assert parse_info(["UNRANEES MIDTOWN DEFEND", "MIDTOWN"]) == ("UNRANKED", "Midtown")


def test_a_loose_match_is_only_taken_from_the_top_line():
    """Words that look like a queue further down (a hero, a menu entry) never become one."""
    assert parse_info(["DEFEND", "TANKED", "MIDTOWN"]) == (None, "Midtown")
    assert game_lists.loose_queue("TANKED ATTACK") == "UNRANKED"  # the top line: it would count


def test_the_german_queues_still_read_exactly():
    assert game_lists.queue("UNGEWERTET ANGRIFF") == "UNGEWERTET"
    assert game_lists.loose_queue("GEWERTET VERTEIDIGUNG") == "GEWERTET"
    assert parse_info(["UNGEWERTET", "ANGRIFF", "NEPAL"]) == ("UNGEWERTET", "Nepal")

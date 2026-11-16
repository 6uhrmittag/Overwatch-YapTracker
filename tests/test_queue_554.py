"""Queue still unknown on bright maps after #537 (#554): the big white title washes out on snow
or glare, and text detection loses it. The title band read alone keeps its start ("UNRODIAEE"),
and hero select keeps looking for the queue while it's up. Replay of all 53 real start samples,
2026-11-09..16, each checked by eye."""

import json
from pathlib import Path

import numpy as np
import pytest

from yaptracker import game_lists, signals
from yaptracker.signals import IN_MATCH_EVERY_S, INFO_TRIES, HeroSelect, read_info, read_title

SAMPLES = json.loads((Path(__file__).parent / "fixtures" / "signals" / "queue-2026-11-16.json")
                     .read_text(encoding="utf-8"))["samples"]  # fmt: skip
CORNER = np.zeros((360, 1170, 3), np.uint8)
BANNER = np.full((60, 780, 3), 200, np.uint8)


def replay(sample: dict, band: bool = True) -> tuple[str | None, str | None]:
    looks, bands = iter(sample["looks"] + [[]] * 3), iter(sample["band"] + [""] * 2)
    return read_info(lambda image: next(looks), CORNER,
                     (lambda image: next(bands)) if band else None)  # fmt: skip


@pytest.mark.parametrize("sample", sorted(SAMPLES))
def test_every_start_sample_reads_the_queue_a_human_can_read_and_never_a_wrong_one(sample):
    assert replay(SAMPLES[sample])[0] == SAMPLES[sample]["queue"]


def test_the_title_band_reads_eight_more_queues():
    before = sum(replay(s, band=False)[0] is not None for s in SAMPLES.values())
    after = sum(replay(s)[0] is not None for s in SAMPLES.values())
    readable = sum(s["queue"] is not None for s in SAMPLES.values())
    assert (before, after, readable) == (25, 33, 33)  # every one a human can read


@pytest.mark.parametrize("read", ["UNRODIAEE", "IINrh EOED", "INRHINR EIL", "INrhuSo", "HNRA.",
                                  "NRHINKEU", "JINRANKED", "UNRO"])  # fmt: skip
def test_a_title_that_kept_its_start_counts(read):
    assert game_lists.title_queue(read) == "UNRANKED"


OTHER_TEXT = ["", "DTKED", "MNE.", "COMBAT", "COMPLETE", "COMMUNICATION", "GENRAL COMBAT NEREAE",
              "HERCE CNS AAS", "PLAY DF THE GAME", "VICTORY MARHME :", "HUNTER", "JUNGLE",
              "ATTACK", "DEFEND"]  # fmt: skip


@pytest.mark.parametrize("read", OTHER_TEXT)
def test_other_text_in_the_title_band_is_no_queue(read):
    assert game_lists.title_queue(read) is None


def test_the_other_queues_still_read_from_the_band():
    assert game_lists.title_queue("COMPETITIVE") == "COMPETITIVE"
    assert game_lists.title_queue("JNGEWERT") == "UNGEWERTET"


def test_the_band_is_read_as_is_then_as_its_darkest_channel():
    pink = np.zeros((360, 1170, 3), np.uint8)
    pink[:] = (230, 120, 250)  # BGR: pink glare; white letters would stay white in all three
    seen = []

    def read_line(image):
        seen.append(image.copy())
        return "" if len(seen) == 1 else "HNRA"

    assert read_title(read_line, pink) == "UNRANKED"
    assert seen[0].shape == (151, 819, 3)  # the top-left of the corner only
    assert (seen[1] == 120).all()  # the darkest channel: the glare goes dark


def test_hero_select_keeps_looking_for_the_queue_while_it_is_up(monkeypatch):
    """Nepal, 2026-11-16: the first looks were white on snow; the camera moves, the glare too."""
    monkeypatch.setattr(signals, "has_bright_text", lambda image, *a, **k: True)
    clock, infos, full_looks, band_reads = [0.0], [], [], []

    def read_band(image):
        band_reads.append(1)
        return "UNRO" if len(band_reads) > 2 * (1 + INFO_TRIES + 3) else ""

    hs = HeroSelect(
        lambda image: "ASSEMBLE YOUR TEAM",
        lambda image: full_looks.append(1) or ["ATTACK", "NEPAL"],
        lambda mode, map_name: infos.append(("start", mode, map_name)),
        lambda: clock[0],
        on_info=lambda mode, map_name: infos.append(("info", mode, map_name)),
        read_band=read_band,
    )
    for _ in range(20):
        hs.update({"heroselect": BANNER, "heroselect_info": CORNER})
        clock[0] += IN_MATCH_EVERY_S
    assert infos == [("start", None, "Nepal"), ("info", "UNRANKED", "Nepal")]
    assert len(full_looks) == 3 * (1 + INFO_TRIES)  # as before: the few full looks, 3 variants
    assert len(band_reads) == 2 * (1 + INFO_TRIES + 3) + 1  # found, then no more reads


def test_a_queue_read_at_once_needs_no_more_looks(monkeypatch):
    monkeypatch.setattr(signals, "has_bright_text", lambda image, *a, **k: True)
    clock, reads = [0.0], []
    hs = HeroSelect(lambda image: "ASSEMBLE YOUR TEAM",
                    lambda image: reads.append(1) or ["UNRANKED", "ATTACK", "NEPAL"],
                    lambda mode, map_name: None, lambda: clock[0],
                    read_band=lambda image: reads.append(1) or "")  # fmt: skip
    for _ in range(10):
        hs.update({"heroselect": BANNER, "heroselect_info": CORNER})
        clock[0] += IN_MATCH_EVERY_S
    assert len(reads) == 1

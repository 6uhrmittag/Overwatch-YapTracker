"""Heroes, maps and queue names from the bundled game lists (#276). No network: the lists are
made at build time by tools/refresh_game_lists.py."""

from pathlib import Path

from yaptracker import game_lists
from yaptracker.capture.source import Region
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import parse


def test_the_lists_are_bundled_with_english_and_german_queue_names():
    data = game_lists.lists()
    assert {"Kiriko", "Zenyatta", "Soldier: 76", "Lúcio"} <= set(data["heroes"])
    assert {"Esperança", "King's Row", "Route 66", "New Junk City"} <= set(data["maps"])
    assert {"UNRANKED", "COMPETITIVE", "UNGEWERTET", "SCHNELLES SPIEL"} <= set(data["queues"])


def test_the_app_never_fetches_them():
    source = Path(game_lists.__file__).read_text(encoding="utf-8")
    assert "urllib" not in source and "http" not in source.split('"""')[2]


def test_misread_heroes_in_comms_lines_are_corrected_unknown_ones_kept():
    said = ["zappy (Zenyata): Group up!", "Pickle (Kirko) to you: Thanks!", "Bo (Qwxzt): Hello!"]
    lines = [OcrLine(text, 0.95, Region(64, 10 + 30 * n, 400, 24)) for n, text in enumerate(said)]
    assert [line.hero for line in parse(lines)] == ["Zenyatta", "Kiriko", "Qwxzt"]

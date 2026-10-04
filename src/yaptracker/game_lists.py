"""Overwatch's heroes, maps and queue names (#276), bundled in data/game_lists.json by
tools/refresh_game_lists.py at build time. OCR'd names are matched against them; what matches
nothing is none rather than garbage ("INRONKED ALU9CK"). Never online at runtime."""

import json
import re
from functools import cache
from pathlib import Path

from rapidfuzz import fuzz, process

LISTS = Path(__file__).parent / "data" / "game_lists.json"
MATCH = 80  # on the letters only: OCR drops spaces ("LIJIANGTOWER") and swaps a letter or two


@cache
def lists() -> dict:
    return json.loads(LISTS.read_text(encoding="utf-8"))


def _letters(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", text.casefold())


def _best(text: str | None, names: list[str], cutoff: int = MATCH) -> str | None:
    if not text or len(_letters(text)) < 2:
        return None
    keys = {name: _letters(name) for name in names}
    found = process.extractOne(_letters(text), keys, scorer=fuzz.ratio, score_cutoff=cutoff)
    return found[2] if found else None


def queue(text: str | None) -> str | None:
    """The queue name at the start of hero select's top line ("UINRANKED ATTACK")."""
    if not text:
        return None
    words = text.split()
    # the queue is the first one or two words; the side ("ATTACK") follows it
    candidates = [" ".join(words[:n]) for n in (2, 1) if len(words) >= n]
    for candidate in candidates:
        if found := _best(candidate, lists()["queues"]):
            return found
    return None


def map_name(text: str | None) -> str | None:
    """The map from hero select's bottom line; a sub-map after "·" is left out ("LIJIANG
    TOWER·NIGHT MARKET" -> Lijiang Tower), so is a cut-off word ("NEPAL NE" -> Nepal)."""
    if not text:
        return None
    head = re.split(r"[·•|]", text)[0].strip()
    if found := _best(head, lists()["maps"]):
        return found
    words = head.split()  # OCR may add a stray word or a cut-off one at the end
    for n in range(len(words) - 1, 0, -1):
        if found := _best(" ".join(words[:n]), lists()["maps"]):
            return found
    return None


def hero(text: str | None) -> str | None:
    """A hero name from a comms-wheel line, e.g. "Zenyata" -> Zenyatta; None if unknown."""
    return _best(text, lists()["heroes"])

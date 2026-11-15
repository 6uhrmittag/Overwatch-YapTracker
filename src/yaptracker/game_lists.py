"""Overwatch's heroes, maps and queue names (#276), bundled in data/game_lists.json by
tools/refresh_game_lists.py at build time. OCR'd names are matched against them; what matches
nothing is none rather than garbage ("INRONKED ALU9CK"). Never online at runtime."""

import json
import re
import string
from functools import cache
from pathlib import Path

from rapidfuzz import fuzz, process

LISTS = Path(__file__).parent / "data" / "game_lists.json"
MATCH = 80  # on the letters only: OCR drops spaces ("LIJIANGTOWER") and swaps a letter or two


def display(text: str) -> str:
    """A map or queue name to show: as stored when it's written like a name ("Throne of Anubis"),
    else in words ("KING'S ROW" -> "King's Row"; str.title makes "King'S Row")."""
    return text if text not in (text.upper(), text.lower()) else string.capwords(text.lower())


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


LOOSE_QUEUE = 70  # a washed-out queue word, after _fold (#537)
LOOSE_MARGIN = 15  # ...and this far ahead of the next queue, so it's never a coin toss
LOOSE_LETTERS = 5


def _fold(text: str) -> str:
    """Overwatch's italic hero-select type: OCR reads its A as O ("INRONKED", #537)."""
    return _letters(text).replace("o", "a")


@cache
def _folded_queues() -> dict[str, str]:
    return {name: _fold(name) for name in lists()["queues"]}


def _candidates(text: str) -> list[str]:
    words = text.split()
    # the queue is the first one or two words; the side ("ATTACK") follows it
    return [" ".join(words[:n]) for n in (2, 1) if len(words) >= n]


def queue(text: str | None) -> str | None:
    """The queue name at the start of hero select's top line ("UINRANKED ATTACK")."""
    for candidate in _candidates(text or ""):
        if found := _best(candidate, lists()["queues"]):
            return found
    return None


def loose_queue(text: str | None) -> str | None:
    """A washed-out queue word on hero select's top line, where queue() finds none: HDR glare
    leaves fragments ("IINRONKE", "UNRANEES") that clearly point at one queue. Real other text
    at that spot (ATTACK, DEFEND, menus) scored at most 62 on Marv's samples."""
    for candidate in _candidates(text or ""):
        if found := queue(candidate):
            return found
        if len(_letters(candidate)) < LOOSE_LETTERS:
            continue
        best = process.extract(_fold(candidate), _folded_queues(), scorer=fuzz.ratio, limit=2)
        if best and best[0][1] >= LOOSE_QUEUE and best[0][1] - best[1][1] >= LOOSE_MARGIN:
            return best[0][2]
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


def map_type(name: str | None) -> frozenset[str]:
    """The map's types ("escort", "hybrid", "control"...) as the API names them (#364); empty
    for a map the lists don't know. `name` as map_name() returns it."""
    return frozenset(lists().get("map_types", {}).get(name or "", ()))

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


def _loose_queue(text: str) -> str | None:
    """HDR glare leaves fragments ("IINRONKE", "ANKED"): the queue they clearly point at. Real
    other text at that spot (ATTACK, DEFEND, menus) scored at most 62 on Marv's samples."""
    if len(_letters(text)) < LOOSE_LETTERS:
        return None
    keys = {name: _fold(name) for name in lists()["queues"]}
    found = process.extract(_fold(text), keys, scorer=fuzz.ratio, limit=2)
    if not found or found[0][1] < LOOSE_QUEUE:
        return None
    if len(found) > 1 and found[0][1] - found[1][1] < LOOSE_MARGIN:
        return None
    return found[0][2]


def queue(text: str | None, loose: bool = False) -> str | None:
    """The queue name at the start of hero select's top line ("UINRANKED ATTACK"); `loose`
    also takes a washed-out one (see _loose_queue)."""
    if not text:
        return None
    words = text.split()
    # the queue is the first one or two words; the side ("ATTACK") follows it
    candidates = [" ".join(words[:n]) for n in (2, 1) if len(words) >= n]
    for candidate in candidates:
        if found := _best(candidate, lists()["queues"]):
            return found
    if loose:
        for candidate in candidates:
            if found := _loose_queue(candidate):
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


def map_type(name: str | None) -> frozenset[str]:
    """The map's types ("escort", "hybrid", "control"...) as the API names them (#364); empty
    for a map the lists don't know. `name` as map_name() returns it."""
    return frozenset(lists().get("map_types", {}).get(name or "", ()))

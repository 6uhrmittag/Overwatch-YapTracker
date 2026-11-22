"""Hero switches from chat (#262): Overwatch writes "Name switched to Ashe (was Sierra)." into
the chat box. They are read from the stored lines whenever a profile opens, so old evenings have
them too and nothing extra is stored. Older lines carry the switch at the end of somebody else's
yap (the row was read as a wrap), which is why it is searched at the end of any line and the
switcher is found by name, not by who the line belongs to.
Only the English wording is known; no German sample yet."""

import re
from dataclasses import dataclass

from yaptracker import game_lists

# At the end of the line. OCR loses the dot, the closing bracket or the hero's end ("(was D.V"),
# reads the icon in front as a mark ("*Name") and a speck after the bracket as a letter.
_SWITCH = re.compile(
    r"(?:^|\s)[^\w\s]*(?P<name>\S+) switched to (?P<to>[^()]+?)\s*"
    r"\(was (?P<was>[^()]+?)(?:\)\.?\s*\S{0,2})?\s*$"
)
STARTS = re.compile(r"^\S+ switched to [^()]+\(was ")  # the row on its own (parser)


@dataclass(frozen=True)
class Switch:
    name: str
    to: str
    was: str
    match_id: int | None = None
    ts: float = 0.0


def find(text: str) -> Switch | None:
    """The switch a line ends with. Both heroes must be real ones (fuzzy, "llari" -> Illari):
    "i switched to tank (was bored)" is somebody talking."""
    m = _SWITCH.search(text)
    if m is None:
        return None
    to, was = game_lists.hero(m["to"]), game_lists.hero(m["was"])
    return Switch(m["name"], to, was) if to and was and to != was else None


def of_player(rows: list[tuple[int | None, float, str]], names: list[str]) -> list[Switch]:
    """One player's switches, oldest first. rows: (match, time, text) of the lines that may hold
    one; names: their name and its other spellings, matched as speakers are (#23)."""
    from yaptracker.identity import MATCH, clean  # identity imports the parser, which imports us
    from yaptracker.players import similarity

    found: dict[tuple, Switch] = {}
    for match_id, ts, text in sorted(rows, key=lambda row: row[1]):
        switch = find(text)
        if switch and any(similarity(clean(switch.name), clean(n)) >= MATCH for n in names):
            # the same switch read into two stored lines counts once
            found.setdefault((match_id, switch.to, switch.was),
                             Switch(switch.name, switch.to, switch.was, match_id, ts))  # fmt: skip
    return list(found.values())


def heroes(switches: list[Switch]) -> list[str]:
    """Every hero the switches name, the latest first."""
    seen: dict[str, None] = {}
    for switch in reversed(switches):
        seen.setdefault(switch.to)
        seen.setdefault(switch.was)
    return list(seen)


def played(switches: list[Switch]) -> dict[int | None, str]:
    """Per match what they played, in order: "Sierra → Vendetta → Ashe"."""
    chains: dict[int | None, list[str]] = {}
    for switch in switches:
        chain = chains.setdefault(switch.match_id, [switch.was])
        if chain[-1] != switch.was:  # a switch in between wasn't read
            chain.append(switch.was)
        chain.append(switch.to)
    return {match_id: " → ".join(chain) for match_id, chain in chains.items()}

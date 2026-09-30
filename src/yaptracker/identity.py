"""Me & my crew (#74): which names are the user and which are their regular group (e.g. Void).

Crew are still players in every log; they just never get a "Look who's back!" greeting.
"""

import re
from dataclasses import dataclass, replace
from typing import Literal

from rapidfuzz import fuzz

from yaptracker.parser import ChatLine

Role = Literal["me", "crew"]
MATCH = 85  # rapidfuzz ratio: OCR slips like "NoodleBonkl" still count, other people don't
EXACT_BELOW = 5  # short names must match exactly - "Bo" is not "Bob"


def clean(name: str) -> str:
    """Chat shows BattleTags without their number: "Marv#2718" is "Marv" on screen."""
    return re.sub(r"#\d+$", "", name.strip())


def same_name(read: str, known: str) -> bool:
    a, b = read.strip().lower(), clean(known).lower()
    if min(len(a), len(b)) < EXACT_BELOW:
        return a == b
    return fuzz.ratio(a, b) >= MATCH


@dataclass(frozen=True)
class Identity:
    me: tuple[str, ...] = ()
    crew: tuple[str, ...] = ()

    def role(self, name: str | None) -> Role | None:
        if not name:
            return None
        if any(same_name(name, n) for n in self.me):
            return "me"
        if any(same_name(name, n) for n in self.crew):
            return "crew"
        return None

    def apply(self, lines: list[ChatLine]) -> list[ChatLine]:
        """Mark own and crew lines; a comms line aimed at one of my names is aimed at "you"."""
        result = []
        for line in lines:
            target = "you" if line.target and self.role(line.target) == "me" else line.target
            result.append(replace(line, role=self.role(line.speaker), target=target))
        return result

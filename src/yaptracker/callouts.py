"""Comms-wheel callouts as the game says them (#290). The wheel has a fixed set of phrases;
OCR's readings are matched against it ("Eall back!" -> "Fall back!", "Enemy llari!" -> "Enemy
Illari!", heroes from the game lists, #276), and a fragment that is no phrase ("My", "/ Enemy")
is no line. Phrases from Marv's debug samples (2026-10-01..03, 126 distinct readings)."""

import re

from rapidfuzz import fuzz, process

from yaptracker import game_lists
from yaptracker.glyphs import GLYPH

MATCH = 80
# Said as is. English client; the German client's wording is added as it shows up in samples.
PHRASES = [
    "Hello!", "Thanks!", "Group up!", "I'm so sorry.", "Good work!", "Fall back!", "Yes.", "No.",
    "I need healing!", "I need help!", "I am on my way.", "You are welcome.", "I'll watch here.",
    "Goodbye.", "Come to me for healing!", "Defend with me!", "Attack with me!", "Push forward!",
    "Ready!", "Acknowledged.", "Understood.",
    "Hallo!", "Danke!", "Sammeln!", "Rückzug!", "Ich brauche Heilung!", "Ich brauche Hilfe!",
]  # fmt: skip
# "Name (Hero) wants to ...": the action alone is the text.
ACTIONS = [
    "wants to attack the objective!", "wants to defend the objective!",
    "wants to push the robot!", "wants to stop the robot!",
    "wants to push the payload!", "wants to stop the payload!",
]  # fmt: skip
_ENEMY = re.compile(
    r"^Enemy\W*(?:[A-Z]\s+)?(?P<hero>.+?)\s*"
    r"(?P<rest>at\s+(?:Low|Critical)\s+Health|sleeping here|discorded here)?\s*!?\W*$",
    re.IGNORECASE,
)
_ULT = re.compile(
    r"^My ultimate \((?P<ult>[^)]+)\)\W*is\s+(?:(?P<ready>ready)|charging\W*(?P<pct>\d+)%)",
    re.IGNORECASE,
)
_RESPAWN = re.compile(r"^Fall back!.*respawn\W*\((?P<s>\d+)s\)", re.IGNORECASE)
_STATES = {"at low health": " at Low Health", "at critical health": " at Critical Health",
           "sleeping here": " sleeping here", "discorded here": " discorded here"}  # fmt: skip


def _letters(text: str) -> str:
    return re.sub(r"[^a-zäöüß]", "", text.casefold())


def normalise(text: str) -> str | None:
    """The callout as the wheel says it, the read text if it's a callout we don't know, or
    None for a fragment that is no callout at all."""
    plain = " ".join(text.replace(GLYPH, " ").split())
    known = _known(plain)
    if known is None and (first := re.match(r"^[^!.]+[!.]", plain)) and first.end() < len(plain):
        known = _known(first.group())  # another line glued on: "Hello! OBACK" -> "Hello!"
    if known is not None:
        return known
    if len(_letters(plain)) <= 5 or _letters(plain) in ("enemy", "myultimate", "wantsto"):
        return None  # "My", "/ Enemy", "En": a piece of a callout, not one
    return plain


def _known(plain: str) -> str | None:
    """The wheel's phrase this reading is, or None."""
    if m := _ULT.match(plain):
        ult = m["ult"].strip()
        return f"My ultimate ({ult}) is ready!" if m["ready"] else \
            f"My ultimate ({ult}) is charging! {m['pct']}%"  # fmt: skip
    if m := _RESPAWN.match(plain):
        return f"Fall back! I'm waiting to respawn! ({m['s']}s)"
    if m := _ENEMY.match(plain):
        hero = game_lists.hero(m["hero"])
        if hero:
            state = _STATES.get(" ".join((m["rest"] or "").lower().split()), "")
            return f"Enemy {hero}{state}!"
    pool = ACTIONS if plain.lower().startswith("wants") else PHRASES
    found = process.extractOne(_letters(plain), {p: _letters(p) for p in pool},
                               scorer=fuzz.ratio, score_cutoff=MATCH)  # fmt: skip
    if found:
        return found[2]
    if plain.lower().startswith("wants to"):  # cut short: the one action it can still be
        cut = _letters(plain)
        close = [a for a in ACTIONS if fuzz.ratio(cut, _letters(a)[: len(cut)]) >= MATCH]
        if len({_letters(a)[: len(cut)] for a in close}) == 1 and len(close) == 1:
            return close[0]
    return None

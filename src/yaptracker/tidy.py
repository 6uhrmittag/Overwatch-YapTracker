"""Tidy up a light match (#336). Windows OCR ("light", #331) misses lines and words, so the
changed chat frames of a light match are kept and read again with the best quality once the game
is idle. That reading runs through a dedup of its own (one stream per match), and each line it
finds is put next to the stored light line:

- the same line (close in time, folded text alike, as in #293): the best reading replaces the
  light one. Lines fixed or deleted by hand stay as they are.
- no such line: the light reader missed it; it's inserted at its real time.
- a light line the best reading never confirms stays as it is.
"""

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from yaptracker.dedup import Dedup, Yap, match_key, text_key
from yaptracker.store.repo import Message

NEAR_S = 15.0  # a line's light and best readings: first seen at most this far apart
ALIKE = 70  # fuzzy ratio of the folded "speaker text" keys (light readings are rougher)


def _who(message: Message) -> str | None:
    return message.hero or message.speaker_raw  # a callout goes by its hero, as in match_key


@dataclass
class TidyMatch:
    """One match's tidy-up: its own dedup, and which stored line each best reading is."""

    match_id: int
    dedup: Dedup = field(default_factory=Dedup)
    links: dict[int, int | None] = field(default_factory=dict)  # yap -> line; None: hands off
    taken: set[int] = field(default_factory=set)  # stored lines already paired
    light: dict[int, tuple] = field(default_factory=dict)  # stored line -> its light reading
    fixed: set[int] = field(default_factory=set)  # lines that now differ from the light reading
    found: int = 0

    def place(self, yap: Yap, stored: list[tuple[Message, bool]]) -> tuple[Message, bool] | None:
        """The stored light line this best reading is, if any: the most alike one close in time.
        (message, hands off): deleted or fixed by hand lines are paired but never changed."""
        key = match_key(yap.best)
        best, best_score = None, ALIKE
        for message, deleted in stored:
            if message.id in self.taken or abs(message.ts - yap.first_seen) > NEAR_S:
                continue
            score = fuzz.ratio(key, text_key(_who(message), message.text))
            if score > best_score or (
                score == best_score
                and best is not None
                and abs(message.ts - yap.first_seen) < abs(best[0].ts - yap.first_seen)
            ):
                best, best_score = (message, deleted or message.edited_at is not None), score
        if best is not None:
            self.taken.add(best[0].id)
            self.light[best[0].id] = shown(best[0])
        return best

    def changed(self, message_id: int, fields: dict) -> None:
        """A line got the best reading: fixed if that differs from its light reading (a reading
        that flips back and forth while it settles counts once, or not at all)."""
        now = (fields["speaker_raw"], fields["text"], fields["hero"], fields["channel"])
        if now == self.light.get(message_id):
            self.fixed.discard(message_id)
        else:
            self.fixed.add(message_id)


def shown(message: Message) -> tuple:
    """What a reading changes about a stored line: speaker, text, hero, channel."""
    return message.speaker_raw, message.text, message.hero, message.channel


def differs(message: Message, fields: dict) -> bool:
    """The best reading would change what's stored."""
    return shown(message) != (fields["speaker_raw"], fields["text"], fields["hero"],
                              fields["channel"])  # fmt: skip

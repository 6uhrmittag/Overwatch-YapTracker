"""Familiar faces (#26): someone you've played with before types in chat -> a chip in Live.

Decided next to the chat reader, not in the UI, so a chip is waiting even if YapTracker's
window was in the background. One per player per match; they stay for the match and clear
themselves when the next one starts, no click needed (#518). Me and my crew never get one (#74).
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from yaptracker.identity import Identity
from yaptracker.store.repo import Store

log = logging.getLogger(__name__)

SEEN_MATCHES = 4  # matches remembered for "one card per player and match"


@dataclass(frozen=True)
class Card:
    player_id: int
    name: str
    verdict: str | None
    note: str  # the first line of your notes
    matches: int  # matches together before this one
    yaps: int
    last_met: float | None
    shown_at: float
    spicy: int = 0  # flagged lines before this match: a heads-up, never a verdict (#77)
    after: bool = False  # heard when the match was read afterwards: "Look who was there!" (#335)
    match_id: int | None = None  # where they were heard: still being read, the card says (#502)


class FamiliarFaces:
    def __init__(
        self,
        store: Store,
        identity: Callable[[], Identity] = Identity,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store, self._identity, self._clock = store, identity, clock
        self._lock = threading.Lock()
        self._cards: list[Card] = []
        self._seen: dict[int | None, set[int]] = {}  # match -> players carded in it

    def heard(
        self, player_id: int | None, match_id: int | None, after: bool = False
    ) -> Card | None:
        """A stored line from this player: a card if you met them in an earlier match.
        after: the line was read after its match was over (#335)."""
        if player_id is None:
            return None
        with self._lock:
            carded = self._seen.pop(match_id, set())
            self._seen[match_id] = carded  # newest last
            if player_id in carded:
                return None
            carded.add(player_id)
            # the tidy-up reads an older match while the next one runs: a few matches, not one
            for old in list(self._seen)[:-SEEN_MATCHES]:
                del self._seen[old]
        player = self._store.player(player_id)
        if player is None:
            return None
        identity = self._identity()  # read now: names added later count for old players too
        spellings = [player.display_name, *self._store.aliases(player_id)]
        if any(identity.role(name) is not None for name in spellings):
            return None  # me, or my crew, under any spelling I read (#168)
        card = card_for(self._store, player_id, match_id, self._clock(), after)
        if card is None or card.matches == 0:
            return None  # first time you meet them: nothing to greet yet
        last_met = card.last_met
        with self._lock:
            self._cards = [c for c in self._cards if c.player_id != player_id] + [card]
        met = time.strftime("%Y-%m-%d", time.localtime(last_met)) if last_met else "?"
        late = ", after the match" if after else ""
        log.info("familiar face: player #%d (last met %s)%s", player_id, met, late)  # ids (#437)
        return card

    def active(self) -> list[Card]:
        """Cards to show, newest first."""
        with self._lock:
            return list(reversed(self._cards))

    def match_started(self, match_id: int | None) -> None:
        """The next match began: the last one's faces go (#518). Anyone already heard in the new
        one stays; whoever writes again gets a fresh card, it's a new match."""
        with self._lock:
            self._cards = [c for c in self._cards if c.match_id == match_id]


def card_for(
    store: Store, player_id: int, match_id: int | None, shown_at: float = 0.0, after: bool = False
) -> Card | None:
    """What you know about a player, seen from this match: the card's contents (#26, #519)."""
    player = store.player(player_id)
    if player is None:
        return None
    matches, yaps, last_met, spicy = store.met_before(player_id, match_id)
    note = (player.notes or "").strip().splitlines()
    return Card(player_id, player.display_name, player.verdict, note[0] if note else "", matches,
                yaps, last_met, shown_at, spicy, after, match_id)  # fmt: skip

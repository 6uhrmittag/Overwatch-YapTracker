"""Familiar faces (#26): someone you've played with before types in chat -> a card in Live.

Decided next to the chat reader, not in the UI, so a card is waiting even if YapTracker's
window was in the background. One card per player per match; it fades after two minutes or
when you click "Got it". Me and my crew never get a card (#74).
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from yaptracker.identity import Identity
from yaptracker.store.repo import Store

SHOW_S = 120  # docs/ui.md: cards fade after ~2 minutes


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
        self._seen: tuple[int | None, set[int]] = (None, set())  # (match, players carded)

    def heard(
        self, player_id: int | None, match_id: int | None, after: bool = False
    ) -> Card | None:
        """A stored line from this player: a card if you met them in an earlier match.
        after: the line was read after its match was over (#335)."""
        if player_id is None:
            return None
        with self._lock:
            if self._seen[0] != match_id:
                self._seen = (match_id, set())
            if player_id in self._seen[1]:
                return None
            self._seen[1].add(player_id)
        player = self._store.player(player_id)
        if player is None:
            return None
        identity = self._identity()  # read now: names added later count for old players too
        spellings = [player.display_name, *self._store.aliases(player_id)]
        if any(identity.role(name) is not None for name in spellings):
            return None  # me, or my crew, under any spelling I read (#168)
        matches, yaps, last_met, spicy = self._store.met_before(player_id, match_id)
        if matches == 0:
            return None  # first time you meet them: nothing to greet yet
        note = (player.notes or "").strip().splitlines()
        card = Card(player_id, player.display_name, player.verdict, note[0] if note else "",
                    matches, yaps, last_met, self._clock(), spicy, after)  # fmt: skip
        with self._lock:
            self._cards = [c for c in self._cards if c.player_id != player_id] + [card]
        return card

    def active(self) -> list[Card]:
        """Cards to show, newest first."""
        now = self._clock()
        with self._lock:
            self._cards = [c for c in self._cards if now - c.shown_at < SHOW_S]
            return list(reversed(self._cards))

    def dismiss(self, player_id: int) -> None:
        with self._lock:
            self._cards = [c for c in self._cards if c.player_id != player_id]

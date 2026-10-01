"""Speakers become players (#23): every chat line belongs to someone, even when OCR slips.

A speaker is matched against every player's name and aliases (the same fuzzy rule as "Me & my
crew", #74: OCR slips like "NoodleBonkl" count, short names must be exact). A new spelling of a
known player becomes an alias; anything else is a new player. My own names never become a
player; crew players are normal players, marked as crew by the crew setting.

The name shown is the spelling read most often, so a first misread ("MoonPebbIe") fixes
itself once the name has been read correctly a few times.
"""

import threading
from collections import Counter
from collections.abc import Callable

from rapidfuzz import fuzz

from yaptracker.identity import EXACT_BELOW, MATCH, Identity, clean
from yaptracker.store.repo import Store

SHAKY_CONFIDENCE = 0.85  # below this, a brand-new name is worth a debug sample (#110)
NEAR = 70  # close to a known name, but not close enough: also worth a look


def similarity(read: str, known: str) -> float:
    a, b = read.lower(), known.lower()
    if min(len(a), len(b)) < EXACT_BELOW:
        return 100.0 if a == b else 0.0
    return fuzz.ratio(a, b)


class PlayerMatcher:
    def __init__(
        self,
        store: Store,
        identity: Callable[[], Identity] = Identity,
        on_shaky: Callable[[str], object] = lambda name: None,
    ) -> None:
        self._store, self._identity, self._on_shaky = store, identity, on_shaky
        self._lock = threading.Lock()
        self._names: dict[str, int] = {name: pid for pid, name in store.player_names()}
        self._reads: dict[int, Counter] = {}  # player -> how often each spelling was read
        self._shown: dict[int, str] = {}

    def reload(self) -> None:
        """After a merge (#28): the names of the merged player now point to the other one."""
        with self._lock:
            self._names = {name: pid for pid, name in self._store.player_names()}
            known = set(self._names.values())
            self._reads = {pid: reads for pid, reads in self._reads.items() if pid in known}
            self._shown = {pid: name for pid, name in self._shown.items() if pid in known}

    def link(self, speaker: str | None, ts: float, confidence: float = 1.0) -> int | None:
        """The player who said this line; None for system lines and for my own lines."""
        if not speaker:
            return None
        if self._identity().role(speaker) == "me":
            return None
        name = clean(speaker)
        with self._lock:
            best_id, best = None, 0.0
            for known, pid in self._names.items():
                score = similarity(name, known)
                if score > best:
                    best_id, best = pid, score
            if best >= MATCH:
                pid = best_id
                if name not in self._names:
                    self._names[name] = pid
                    self._store.add_alias(pid, name)
                self._store.player_seen(pid, ts)
            else:
                pid = self._store.add_player(name, ts)
                self._names[name] = pid
                self._shown[pid] = name
                if confidence < SHAKY_CONFIDENCE or best >= NEAR:
                    self._on_shaky(name)
            self._count(pid, name)
            return pid

    def _count(self, pid: int, name: str) -> None:
        reads = self._reads.setdefault(pid, Counter())
        reads[name] += 1
        most = reads.most_common(1)[0][0]
        if self._shown.get(pid) is None:
            self._shown[pid] = most
        elif most != self._shown[pid]:  # read more often than the name shown so far
            self._shown[pid] = most
            self._store.rename_player(pid, most)

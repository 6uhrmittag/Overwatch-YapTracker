"""Each chat line once (#18). The chat box shows a line for ~9 s while it scrolls up, and shows
older lines again whenever the chat is opened. Dedup keeps the recent lines in order and says
which lines of a frame are new, and when an earlier line got a better reading.

Matching, checked on real frames (#18):
- A frame's yap lines are aligned with the recent lines in order (longest common subsequence,
  fuzzy), so a misread name ("VoidGrowned") or one missing line doesn't break it.
- New lines only ever arrive at the bottom: unmatched lines *below* the last match are new;
  unmatched lines above it are older chat (the chat was opened) or misreads, never new.
- Lines fade ~9 s after they appear. An older line only matches next to a matched neighbour,
  so a "gg" typed again later counts again, while a reopened chat full of old lines doesn't.
- The best reading is the one read most often, then the most confident: background text glued
  to a line ("Oops XD EM PORTUGAL") can be read with high confidence once, but not every time.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from yaptracker.identity import clean
from yaptracker.parser import ChatLine

YAP_KINDS = ("message", "comms", "system")
SAME = 85  # fuzzy ratio of "speaker: text" for two readings of the same line
FADE_S = 10.0  # a line is visible for ~9 s after it first appears (measured on real frames)
KEEP = 40  # recent lines to match against; an open chat box shows about 8


# Map text or a nameplate behind the box gets glued to the end of a line: "gg TOURING EM PORTU".
_GLUED = re.compile(r"(?:\s+[A-Z\u00c0-\u00de0-9]{2,}[!.,]*)+$")


def key(line: ChatLine) -> str:
    return (f"{clean(line.speaker)}: {line.text}" if line.speaker else line.text).lower()


def match_key(line: ChatLine) -> str:
    """key() without glued capitals, as long as some lower-case text is left ("GG WP" stays)."""
    text = _GLUED.sub("", line.text)
    text = text if re.search(r"[a-z]", text) else line.text
    return (f"{clean(line.speaker)}: {text}" if line.speaker else text).lower()


def _stored(line: ChatLine) -> tuple:
    """What a better reading would change in the database."""
    return line.kind, line.speaker, line.hero, line.text, line.flagged


@dataclass
class Yap:
    """One chat line as it gets stored, with every reading of it."""

    id: int
    first_seen: float
    readings: Counter = field(default_factory=Counter)  # key -> times read
    lines: dict[str, ChatLine] = field(default_factory=dict)  # key -> its most confident read
    match_keys: set[str] = field(default_factory=set)
    last: ChatLine | None = None  # the reading from the newest frame (its box is on that frame)

    @property
    def best(self) -> ChatLine:
        best = max(self.readings, key=lambda k: (self.readings[k], self.lines[k].confidence))
        return self.lines[best]

    def add(self, line: ChatLine) -> None:
        k = key(line)
        self.readings[k] += 1
        if k not in self.lines or line.confidence > self.lines[k].confidence:
            self.lines[k] = line
        self.match_keys.add(match_key(line))
        self.last = line

    def similarity(self, k: str) -> float:
        return max(fuzz.ratio(k, known) for known in self.match_keys)


class Dedup:
    def __init__(self, keep: int = KEEP, fade_s: float = FADE_S) -> None:
        self._keep, self._fade_s = keep, fade_s
        self.recent: list[Yap] = []
        self._next_id = 1

    def update(self, ts: float, lines: list[ChatLine]) -> tuple[list[Yap], list[Yap]]:
        """(new, improved): yaps first seen in this frame, and earlier ones read better now."""
        chat_open = any(line.kind == "input" for line in lines)
        lines = [line for line in lines if line.kind in YAP_KINDS]
        pairs = self._align([match_key(line) for line in lines])
        pairs = [p for n, p in enumerate(pairs) if self._valid(ts, pairs, n, chat_open)]
        improved = []
        for i, j in pairs:
            yap = self.recent[j]
            before = _stored(yap.best)
            yap.add(lines[i])
            if _stored(yap.best) != before:
                improved.append(yap)
        last = pairs[-1][0] if pairs else -1
        new = []
        for line in lines[last + 1 :]:
            yap = Yap(self._next_id, ts)
            yap.add(line)
            self._next_id += 1
            new.append(yap)
        self.recent = (self.recent + new)[-self._keep :]
        return new, improved

    def _align(self, keys: list[str]) -> list[tuple[int, int]]:
        """Matched (line, recent) index pairs, in order: most matches, then the newest entries,
        then the most similar readings.

        Lines on screen are the most recent ones, so among equally many matches the newest
        entries win, even if an older one was once read a little more exactly (#134). For the
        same entries, similarity decides ("hi" matches "hi", not "o/" by the same speaker).
        """
        n, m = len(keys), len(self.recent)
        score = [[(0, 0, 0.0)] * (m + 1) for _ in range(n + 1)]
        diagonal = [[None] * (m + 1) for _ in range(n + 1)]  # the score via matching i with j
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                best = max(score[i - 1][j], score[i][j - 1])
                similar = self.recent[j - 1].similarity(keys[i - 1])
                if similar >= SAME:
                    count, newest, total = score[i - 1][j - 1]
                    diagonal[i][j] = (count + 1, newest + j, total + similar)
                    best = max(best, diagonal[i][j])
                score[i][j] = best
        # Walking back from the newest entry and matching as soon as it's as good: on a tie the
        # newest entry wins, so "Group up!" said again isn't paired with the old one (#129).
        pairs, i, j = [], n, m
        while i and j:
            if diagonal[i][j] == score[i][j]:
                pairs.append((i - 1, j - 1))
                i, j = i - 1, j - 1
            elif score[i][j] == score[i - 1][j]:
                i -= 1
            else:
                j -= 1
        return pairs[::-1]

    def _valid(self, ts: float, pairs: list[tuple[int, int]], n: int, chat_open: bool) -> bool:
        """A faded line can only be on screen again in an opened chat, next to its neighbours."""
        i, j = pairs[n]
        if chat_open or ts - self.recent[j].first_seen <= self._fade_s:
            return True
        neighbours = pairs[max(0, n - 1) : n] + pairs[n + 1 : n + 2]
        return any(abs(i - a) == 1 and 1 <= abs(j - b) <= 2 for a, b in neighbours)

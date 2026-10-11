"""Each chat line once (#18). The chat box shows a line for ~9 s while it scrolls up, and shows
older lines again whenever the chat is opened. Dedup keeps the recent lines in order and says
which lines of a frame are new, and when an earlier line got a better reading.

Matching, checked on real frames (#18):
- A frame's yap lines are aligned with the recent lines in order (longest common subsequence,
  fuzzy), so a misread name ("MoonPebbIe") or one missing line doesn't break it.
- New lines only ever arrive at the bottom: unmatched lines *below* the last match are new;
  unmatched lines above it are older chat (the chat was opened) or misreads, never new.
- Lines fade ~9 s after they appear. An older line only matches next to a matched neighbour,
  so a "gg" typed again later counts again, while a reopened chat full of old lines doesn't.
- The best reading is the one read most often, then the most confident: background text glued
  to a line ("Oops XD EM PORTUGAL") can be read with high confidence once, but not every time.
"""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field, replace

from rapidfuzz import fuzz

from yaptracker.glyphs import GLYPH
from yaptracker.identity import clean
from yaptracker.parser import ChatLine
from yaptracker.quality import GOOD

YAP_KINDS = ("message", "comms", "system")
SAME = 85  # fuzzy ratio of "speaker: text" for two readings of the same line
FADE_S = 10.0  # a line is visible for ~9 s after it first appears (measured on real frames)
# After the chat box closes, the history it showed stays up to ~16 s after the last frame with
# its prompt (54 samples, 2026-10-01), then fades (#179).
HISTORY_S = 20.0
KEEP = 40  # recent lines to match against; an open chat box shows about 8


# Map text or a nameplate behind the box gets glued to the end of a line: "gg TOURING EM PORTU".
_GLUED = re.compile(r"(?:\s+[A-Z\u00c0-\u00de0-9]{2,}[!.,]*)+$")


def key(line: ChatLine) -> str:
    return (f"{clean(line.speaker)}: {line.text}" if line.speaker else line.text).lower()


# Punctuation OCR adds or drops between readings of one line ("[Name]: : WW!" / "ww", #184).
_PUNCTUATION = re.compile(r"[\s:：;.,!?'\"]+")


_ACCENTS = re.compile(r"[äöüÄÖÜßéèêáàíóúñçÉÈ]")


def _fold(text: str) -> str:
    """For matching only (#293): umlauts and accents to their base letters, ß as the B OCR
    confuses it with, no ◇, punctuation and emoticon noise gone (">:3" vs ".3")."""
    plain = unicodedata.normalize("NFKD", text.replace("ß", "b").replace(GLYPH, " "))
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    return re.sub(r"[^\w\s]", " ", plain)


def _accented(text: str) -> bool:
    return bool(_ACCENTS.search(text))


def match_key(line: ChatLine) -> str:
    """key() without glued capitals, as long as some lower-case text is left ("GG WP" stays),
    and without punctuation: readings that differ only in case or punctuation are one line.
    A callout goes by its hero, not its speaker (#290): a hero is on a team once, and a garbled
    name ("MW: Enemy Siera" for "you: Enemy Sierra!") is then the same line."""
    who = line.hero if line.kind == "comms" and line.hero else line.speaker
    return text_key(who, line.text)


def text_key(who: str | None, text: str) -> str:
    """match_key() of a speaker (or callout hero) and a text, also for stored lines (#336)."""
    unglued = _GLUED.sub("", text)
    text = unglued if re.search(r"[a-z]", unglued) else text
    key = _PUNCTUATION.sub(" ", f"{clean(who) if who else ''} {_fold(text)}")
    return " ".join(key.split()).lower()


NEAR_NAME = 70  # a callout's speaker this close to its hero's recent speaker is a misreading


def hero_speaker(line: ChatLine, recent: list["Yap"]) -> str | None:
    """The name a callout's hero had in recent lines, when this line's name is a near miss of
    it (#424): "MoanPabble (Doctrine)" next to "MoonPebble (Doctrine)" lines is MoonPebble.
    One hero is one player in a match. None when the line's name is fine or nothing fits."""
    if line.kind != "comms" or not line.hero or not line.speaker:
        return None
    same_hero = [y.best for y in recent if y.best.kind == "comms" and y.best.hero == line.hero]
    names = Counter(said.speaker for said in same_hero if said.speaker)
    if not names or line.speaker in names:
        return None
    name = names.most_common(1)[0][0]
    return name if fuzz.ratio(line.speaker.lower(), name.lower()) >= NEAR_NAME else None


def _plain(text: str) -> str:
    """The text without its "◇" marks, to compare readings of one line."""
    return " ".join(text.replace(GLYPH, " ").split())


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
    after: int | None = None  # read between known lines: the yap right above it (#423)
    last: ChatLine | None = None  # the reading from the newest frame (its box is on that frame)

    @property
    def best(self) -> ChatLine:
        """A good reading beats weak ones however often those were read, so a bright frame
        can't flip it back (#195); then the most frequent, then the best scored."""

        def rank(k: str) -> tuple:
            q = self.lines[k].quality
            # among good readings the one with umlauts wins, however often the plain one was
            # read: the Latin model only adds them when the line or its picture shows them (#293)
            return (q >= GOOD, q >= GOOD and _accented(self.lines[k].text), self.readings[k], q)

        best = self.lines[max(self.readings, key=rank)]
        # ◇ when at least half of the good readings saw the icon (#402). One reading out of many
        # was enough before (#259), and the map behind a line changes while it's on screen:
        # sooner or later something bright sat right after the text. Icon callouts always
        # carry theirs (parser), so the comms icons that came and went are covered.
        plain = _plain(best.text)
        same = [k for k, line in self.lines.items()
                if line.quality >= GOOD and _plain(line.text) == plain] or [key(best)]  # fmt: skip
        marked = [k for k in same if GLYPH in self.lines[k].text]
        if 2 * sum(self.readings[k] for k in marked) >= sum(self.readings[k] for k in same) > 0:
            if GLYPH in best.text or not marked:
                return best
            return replace(best, text=self.lines[marked[0]].text)
        return replace(best, text=plain) if GLYPH in best.text else best

    @property
    def weak(self) -> bool:
        """No good reading yet: worth reading again while it's on screen (#195)."""
        return self.best.quality < GOOD

    def add(self, line: ChatLine) -> None:
        k = key(line)
        self.readings[k] += 1
        if k not in self.lines or line.quality > self.lines[k].quality:
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
        self._open_until = -1.0  # the history stays on screen for a while after the chat closes

    def update(self, ts: float, lines: list[ChatLine]) -> tuple[list[Yap], list[Yap]]:
        """(new, improved): yaps first seen in this frame, and earlier ones read better now."""
        if any(line.kind == "input" for line in lines):
            self._open_until = ts + HISTORY_S
        # Sending a line closes the chat box, but the history it showed fades only later (#179):
        # "[x]: Hello!" from 20 s ago is still the same line, not a new one.
        chat_open = ts <= self._open_until
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
        missed = self._between(ts, lines, pairs)
        last = pairs[-1][0] if pairs else -1
        new = []
        for line in lines[last + 1 :]:
            yap = Yap(self._next_id, ts)
            yap.add(line)
            self._next_id += 1
            new.append(yap)
        self.recent = (self.recent + new)[-self._keep :]
        return [yap for _, yap in missed] + new, improved

    def _between(self, ts: float, lines: list[ChatLine], pairs: list) -> list[tuple[int, Yap]]:
        """Rows between two known lines that follow each other, matching nothing: lines an
        earlier read missed (#423). Only new rows were the ones below the last known line, so
        "[MoonPebble]: Tracks" and "You endorsed Nibbler!", seen later between two stored lines,
        were never stored. Only good readings that look like no known line count; where known
        lines were skipped in between, a row may be one of them misread, so it doesn't."""
        found: list[tuple[int, Yap]] = []
        for (i0, j0), (i1, j1) in zip(pairs, pairs[1:], strict=False):
            if j1 != j0 + 1:
                continue
            above, below = self.recent[j0], self.recent[j1]
            rows = lines[i0 + 1 : i1]
            for step, line in enumerate(rows, start=1):
                k = match_key(line)
                if line.quality < GOOD or any(y.similarity(k) >= SAME for y in self.recent):
                    continue
                # between the lines around it, so it sorts where it was said
                gap = below.first_seen - above.first_seen
                at = above.first_seen + gap * step / (len(rows) + 1)
                yap = Yap(self._next_id, min(ts, at), after=above.id)
                yap.add(line)
                self._next_id += 1
                found.append((j0, yap))
        if found:  # into the history at their place, for the next reads
            below: dict[int, list[Yap]] = {}
            for j, yap in found:
                below.setdefault(j, []).append(yap)
            self.recent = [y for j, old in enumerate(self.recent) for y in (old, *below.get(j, []))]
        return found

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
            if diagonal[i][j] == score[i][j] and score[i - 1][j] == score[i][j]:
                i -= 1  # an earlier row is just as good for this entry: the stored line stays
                # where it was and this row is a repeat below it (#296), not the line itself
            elif diagonal[i][j] == score[i][j]:
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

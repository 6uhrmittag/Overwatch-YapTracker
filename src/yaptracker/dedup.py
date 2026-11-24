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

import itertools
import re
import unicodedata
from collections import Counter
from collections.abc import Iterator
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field, replace

from rapidfuzz import fuzz

from yaptracker import game_lists
from yaptracker.glyphs import GLYPH, unnamed
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
PART_MIN = 4  # letters: a shorter reading isn't taken for the beginning of another line (#432)
UNSTORED_S = 60.0  # a row seen-but-not-stored is forgotten after this long out of sight (#425)


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
    plain = unicodedata.normalize("NFKD", unnamed(text).replace("ß", "b").replace(GLYPH, " "))
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


# A hero switch as match_key() has it: "name switched to ashe was sierra" (#262).
_SWITCH_KEY = re.compile(r"\bswitched to (.+?) was (.+?)$")


def _switch(k: str) -> tuple[str, str] | None:
    """The two heroes of a hero switch key, as real hero names; None if it isn't one."""
    m = _SWITCH_KEY.search(k)
    if m is None:
        return None
    to, was = game_lists.hero(m[1]), game_lists.hero(m[2])
    return (to, was) if to and was else None


def _similar(a: str, b: str) -> float:
    """Fuzzy ratio of two keys; two hero switches with other heroes are never one line (#571):
    "Bo switched to Ana (was Mercy)" and "Bo switched to Kiriko (was Ana)" score ~90."""
    ratio = fuzz.ratio(a, b)
    if ratio >= SAME and "switched to" in a and "switched to" in b:
        one, other = _switch(a), _switch(b)
        if one and other and one != other:
            return 0.0
    return ratio


def stored_as(k: str, keys: list[str], prefix: bool = False) -> bool:
    """A reading's match_key() is one of these keys (#504): alike as in dedup, or, with
    `prefix`, the start of one with junk glued on ("You endorsed X! NEXT TIER: 4071/50000").
    The caller allows that for three words of text at least, so "Bo: gg" isn't "Bo: gg wp"."""
    return any(_similar(k, s) >= SAME or (prefix and s.startswith(k + " ")) for s in keys)


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


def _same_speaker(a: str | None, b: str | None) -> bool:
    """Two readings of one name (light OCR: "uwultrar rww", a "]" read as "l")."""
    if not a or not b:
        return a == b
    return fuzz.ratio(_folded(clean(a)), _folded(clean(b))) >= NEAR_NAME


def _folded(text: str) -> str:
    """Folded, lower-case, single-spaced text: to see whether one reading begins another."""
    return " ".join(_fold(text).lower().split())


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
    cut: str | None = None  # folded text of a cut reading a longer one completed (#587)

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
        start, read = _folded(best.text), self.readings[key(best)]
        # read at least as often: map text glued once to the end ("gg TOURING EM") stays out
        longer = [line for k, line in self.lines.items()
                  if line.quality >= GOOD and (self.readings[k] >= read or self._completes(line))
                  and _folded(line.text).startswith(start)
                  and len(_folded(line.text)) > len(start)]  # fmt: skip
        if longer:  # light OCR read the beginning first ("so please n"): the whole line (#432)
            best = max(longer, key=lambda line: len(_folded(line.text)))
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

    def _completes(self, line: ChatLine) -> bool:
        """A reading that goes on where the cut one stopped (#587): wins however often the cut
        one was read. Glued map capitals don't make a reading longer."""
        return self.cut is not None and _folded(_GLUED.sub("", line.text)).startswith(
            self.cut + " "
        )

    def total(self) -> int:
        """How often this line was read, all readings together."""
        return sum(self.readings.values())

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
        return max(_similar(k, known) for known in self.match_keys)


class Dedup:
    def __init__(self, keep: int = KEEP, fade_s: float = FADE_S,
                 ids: Iterator[int] | None = None) -> None:  # fmt: skip
        self._keep, self._fade_s = keep, fade_s
        self.recent: list[Yap] = []
        # Shared by a live and a kept stream read side by side (#597): yap ids never clash.
        self.ids = ids if ids is not None else itertools.count(1)
        self._open_until = -1.0  # the history stays on screen for a while after the chat closes
        self.unstored: list[ChatLine] = []  # rows seen twice but never stored, this read (#425)
        self._between_seen: dict[tuple[str, int], int] = {}  # a missed line, read how often
        # key -> (times seen, last seen, first seen)
        self._seen_unstored: dict[str, tuple[int, float, float]] = {}
        # This read's reported rows, by id(): (the known line below it, rows up from that, first
        # seen): where adopt() puts them (#602).
        self._where: dict[int, tuple[Yap, int, float]] = {}

    def update(self, ts: float, lines: list[ChatLine]) -> tuple[list[Yap], list[Yap]]:
        """(new, improved): yaps first seen in this frame, and earlier ones read better now."""
        if any(line.kind == "input" for line in lines):
            self._open_until = ts + HISTORY_S
        # Sending a line closes the chat box, but the history it showed fades only later (#179):
        # "[x]: Hello!" from 20 s ago is still the same line, not a new one.
        chat_open = ts <= self._open_until
        lines = [line for line in lines if line.kind in YAP_KINDS]
        pairs = self._align([match_key(line) for line in lines])
        # Three known lines in order, two of them long faded: the opened chat's history, also
        # when its input row wasn't read (light OCR, #432), so they aren't new again.
        faded = sum(1 for _, j in pairs if ts - self.recent[j].first_seen > self._fade_s)
        history = len(pairs) >= 3 and faded >= 2
        pairs = [p for n, p in enumerate(pairs) if self._valid(ts, pairs, n, chat_open or history)]
        improved = []
        for i, j in pairs:
            yap = self.recent[j]
            before = _stored(yap.best)
            yap.add(lines[i])
            if _stored(yap.best) != before:
                improved.append(yap)
        on_screen = {self.recent[j].id for _, j in pairs}  # before _between moves the indexes
        known = [(i, self.recent[j]) for i, j in pairs]
        missed = self._between(ts, lines, pairs)
        last = pairs[-1][0] if pairs else -1
        new = []
        for line in lines[last + 1 :]:
            whole = self._part_of(line, ts, on_screen)
            if whole is not None:  # the beginning of a known line, or that line read whole
                if len(_folded(line.text)) > len(_folded(whole.best.text)):
                    before = _stored(whole.best)
                    cut = _folded(whole.best.text)
                    whole.add(line)
                    if whole.total() > 3:  # read cut again and again: any good whole reading
                        whole.cut = cut
                    if _stored(whole.best) != before and whole not in improved:
                        improved.append(whole)
                continue
            yap = Yap(next(self.ids), ts)
            yap.add(line)
            new.append(yap)
        self.recent = (self.recent + new)[-self._keep :]
        used = {i for i, _ in pairs} | set(range(last + 1, len(lines)))
        used |= {i for i, line in enumerate(lines) if any(line is y.last for _, y in missed)}
        rows = [(i, line) for i, line in enumerate(lines) if i not in used]
        self.unstored = self._unstored(ts, rows, known)
        return [yap for _, yap in missed] + new, improved

    def _unstored(self, ts: float, rows: list[tuple[int, ChatLine]],
                  known: list[tuple[int, Yap]]) -> list[ChatLine]:  # fmt: skip
        """Rows read well that look like no known line, yet weren't stored (#425): above the
        oldest known line of an opened chat box, or between known lines where one was skipped.
        The second time one is seen it's reported, once: the reader stores it with adopt() if
        it isn't in the database either (#602)."""
        self._seen_unstored = {k: v for k, v in self._seen_unstored.items()
                               if ts - v[1] <= UNSTORED_S}  # fmt: skip
        report, self._where = [], {}
        for i, line in rows:
            k = match_key(line)
            if line.quality < GOOD or any(y.similarity(k) >= SAME for y in self.recent):
                continue
            seen, _, first = self._seen_unstored.get(k, (0, ts, ts))
            self._seen_unstored[k] = (seen + 1, ts, first)
            if seen + 1 == 2:
                report.append(line)
                # only rows below the last known line are new, so every row here has one below
                at, below = next((n, yap) for n, yap in known if n > i)
                self._where[id(line)] = (below, at - i, first)
        return report

    def adopt(self, line: ChatLine) -> tuple[Yap, Yap] | None:
        """A row this read reported becomes a line after all (#602): (it, the known line right
        below it). Only with an older known line than that one: the chat box shows lines without
        holes, so a row above a known line that isn't the known line before it was said between
        the two and missed. Above the oldest line known, it's the history from before anything
        was read (#179): None. It goes into the history above the line below it, so the next
        reads know it; at the time it was first seen, but never after the line below it."""
        where = self._where.pop(id(line), None)
        if where is None or where[0] not in self.recent[1:]:
            return None
        below, up, first = where
        yap = Yap(next(self.ids), min(first, below.first_seen - 0.001 * up))
        yap.add(line)
        self.recent.insert(self.recent.index(below), yap)
        self._seen_unstored.pop(match_key(line), None)
        return yap, below

    def piece_of(self, line: ChatLine) -> Yap | None:
        """A known line by a similar name that starts with this row, or that this row starts
        with (#602): one of the two is a cut reading of the other (#432), not a line of its own.
        Three words at least, so "gg" isn't taken for the start of "gg wp"."""
        text = _folded(_GLUED.sub("", line.text))
        for yap in reversed(self.recent):
            said = yap.best
            if said.kind != line.kind or not _same_speaker(said.speaker, line.speaker):
                continue
            short, long = sorted((_folded(_GLUED.sub("", said.text)), text), key=len)
            if len(short.split()) >= 3 and long.startswith(short + " "):
                return yap
        return None

    def _part_of(self, line: ChatLine, ts: float | None = None,
                 on_screen: AbstractSet[int] = frozenset()) -> "Yap | None":  # fmt: skip
        """A recent line this row is the beginning of, or whose beginning it is, said by a
        similar name (#432): light OCR read "so please n" and "were in the" off longer lines.
        A longer row completes a known line read at most twice, or a callout read often but
        still fresh and not on screen next to it (#587): its wrapped second row ("charging!
        42%") came into the box seconds after "My ultimate (EMP) is" was read again and again.
        Only callouts: their texts are fixed, so one that starts another is a cut reading; a
        typed "nice" and then "nice shot" are two lines. Glued map text doesn't count."""
        text = _folded(line.text)
        if len(text) < PART_MIN:
            return None
        for yap in reversed(self.recent):
            said = yap.best
            if said.kind != line.kind or not _same_speaker(said.speaker, line.speaker):
                continue
            other = _folded(said.text)
            if len(other) < PART_MIN or other == text:
                continue
            if other.startswith(text):
                return yap
            fresh = (line.kind == "comms" and ts is not None and ts - yap.first_seen <= FADE_S
                     and yap.id not in on_screen
                     and _folded(_GLUED.sub("", line.text)).startswith(other + " "))  # fmt: skip
            if text.startswith(other) and (yap.total() <= 2 or fresh):
                return yap
        return None

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
                if self._part_of(line) is not None:
                    continue  # a piece of a known line (#432)
                seen = self._between_seen.get((k, above.id), 0) + 1
                self._between_seen[(k, above.id)] = seen
                if seen < 2:
                    continue  # read the same way twice first: never from one reading (#432)
                # between the lines around it, so it sorts where it was said
                gap = below.first_seen - above.first_seen
                at = above.first_seen + gap * step / (len(rows) + 1)
                yap = Yap(next(self.ids), min(ts, at), after=above.id)
                yap.add(line)
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

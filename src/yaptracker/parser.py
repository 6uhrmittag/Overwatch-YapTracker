"""OCR lines -> chat lines: kind, channel, speaker, hero, text (formats verified in #13).

Shapes seen on real 2560x1440 screenshots (brackets wrap the name, not the channel):
  [Name]: text                          typed chat; team/match/group is only known from the icon
                                        colour (#14), so channel stays "unknown" here
  Name (Hero): text                     comms wheel -> team
  Name (Hero) to you: text              ... with a target
  Name (Hero) to Other (Hero): text
  Name (Hero) wants to stop the robot!  ... without a colon
  [Name] started playing Overwatch.     system (bracketed name, no colon; a few known phrases)
  [Name] text                           any other phrase: typed chat, OCR lost the colon
  You have joined a group!              system without a name (_NAMELESS_SYSTEM)
  [Match] ...                           input line of the open chat box -> ignored
Long messages wrap onto a closer-spaced line without icon; those are joined.
"""

import re
import statistics
from dataclasses import dataclass, replace

from yaptracker.capture.source import Region
from yaptracker.glyphs import GLYPH
from yaptracker.ocr.engine import OcrLine
from yaptracker.quality import reading_quality

_COLON = r"\s*[:：;]\s*"
_TYPED = re.compile(r"^\[(?P<name>[^\]\s]+)\][^\s:：]?" + _COLON + r"(?P<text>.*)$")
# The closing bracket is sometimes misread ("[Name1: hi"); keep what OCR saw as the name.
_TYPED_NO_BRACKET = re.compile(r"^\[(?P<name>[^\]\s:：]+)" + _COLON + r"(?P<text>.*)$")
_COMMS = re.compile(
    r"^(?P<name>[^\s\[\]()]+)\s*\((?P<hero>[^)]+)\)"
    r"(?:\s+to\s+(?P<target>you|[^\s()]+)(?:\s*\((?P<target_hero>[^)]+)\))?)?"
    r"(?:" + _COLON + r"(?P<text>.*)|\s+(?P<action>wants to .*))$"
)
_COMMS_START = re.compile(r"^[^\s\[\]()]+\s*\([^)]+\)")
_SYSTEM_NAMED = re.compile(r"^\[(?P<name>[^\]]+)\]\s+(?P<text>[^:：\s].*)$")
# The few system lines with a [Name] in front (#13, #184). Any other "[Name] text" is typed
# chat whose colon OCR lost ("[Name] WW", "[Name] fun game :3").
_NAMED_SYSTEM = (
    r"started playing\b",
    r"(?:has )?joined the (?:game|group)\b",
    r"(?:has )?left the (?:game|group)\b",
    r"is now (?:online|offline|the group leader)\b",
    r"invited you\b",
    r"was invited to the group\b",  # Void's crop (#228)
    r"(?:accepted|declined) your\b",
)
_SYSTEM_PHRASE = re.compile(r"^(?:" + "|".join(_NAMED_SYSTEM) + ")", re.IGNORECASE)
# A colon OCR read twice ("[Name]: : WW") is not part of the text; ":3" and ":)" are.
_STRAY_COLON = re.compile(r"^(?:[:：;.]\s+)+")
# System lines without a [Name] (yellow i icon). Each is how a line starts; add new ones here as
# the debug samples (#63) show them.
_NAMELESS_SYSTEM = (
    r"You have joined a group",
    r"You have left the group",
    r"You left the group",
    r"You endorsed .+",
    r"\d+ friends? playing Overwatch",  # "1 friend playing Overwatch." (#101)
    r"Endorsement Received",  # after a match, in the menu (#176)
    r"\S+'s group wants to stay as a team",
)
_SYSTEM_PLAIN = re.compile(r"^(?:" + "|".join(_NAMELESS_SYSTEM) + ")")
# Comms-wheel callouts that end with an icon (#259; seen in Marv's samples: 👍, the group-up
# arrows, the fall-back arrow, a health cross). "Hello!" and "Enemy X!" have none.
ICON_CALLOUTS = frozenset({"thanks!", "group up!", "fall back!", "i need healing!"})
_INPUT = re.compile(r"^\[(Match|Team|Group)\](?!" + _COLON + ")")
_PROMPT = re.compile(r"^\[?(?P<word>[A-Za-z]{3,6})\](?!\s*" + _COLON + ")")
_PROMPTS = ("Match", "Team", "Group")
_REPORT = re.compile(r"\s*\[Report\]\s*$")


@dataclass(frozen=True)
class ChatLine:
    kind: str  # message | comms | system | input | cut | unknown
    channel: str  # team | match | group | system | unknown
    text: str
    confidence: float
    box: Region
    speaker: str | None = None
    hero: str | None = None
    target: str | None = None  # "you" or a name, for comms lines
    flagged: bool = False  # Overwatch appended a [Report] link
    role: str | None = None  # "me" / "crew" once the identity is applied (#74)
    head: Region | None = None  # the first row: where the channel icon sits (#173)

    @property
    def quality(self) -> float:
        """Confidence minus junk characters (#195): which reading of a line to keep."""
        return reading_quality(self.text, self.confidence)


def _starts_line(text: str) -> bool:
    return any(p.match(text) for p in (_TYPED, _TYPED_NO_BRACKET, _COMMS_START, _SYSTEM_NAMED,
                                       _SYSTEM_PLAIN, _INPUT))  # fmt: skip


def _misread_prompt(text: str) -> bool:
    """The chat field's prompt read badly: "[Mateh] hi", "Match] hi" (#254). The frame check
    (input_row) is the main guard; this catches a misread prompt it missed. Never a system
    line like "[Teams] started playing Overwatch."."""
    from rapidfuzz import fuzz

    m = _PROMPT.match(text)
    if m is None or _SYSTEM_PHRASE.match(text[m.end() :].strip()):
        return False
    return any(fuzz.ratio(m["word"].lower(), p.lower()) >= 80 for p in _PROMPTS)


def _classify(text: str, confidence: float, box: Region) -> ChatLine:
    flagged = bool(_REPORT.search(text))
    text = _REPORT.sub("", text)
    line = ChatLine("unknown", "unknown", text, confidence, box, flagged=flagged)
    if _INPUT.match(text) or _misread_prompt(text):
        return replace(line, kind="input")
    if m := _COMMS.match(text):
        # Text can be empty: "Name (Hero) to Other (Hero):" with the message on the next line.
        said = (m["text"] or m["action"] or "").strip()
        # Its icon is always there, even when the picture check missed it (#259).
        if said.lower() in ICON_CALLOUTS:
            said = f"{said} {GLYPH}"
        return replace(line, kind="comms", channel="team", speaker=m["name"], hero=m["hero"],
                       target=m["target"], text=said)  # fmt: skip
    if (m := _TYPED.match(text)) or (m := _TYPED_NO_BRACKET.match(text)):
        said = _STRAY_COLON.sub("", m["text"].strip())
        return replace(line, kind="message", speaker=m["name"], text=said)
    if m := _SYSTEM_NAMED.match(text):
        if _SYSTEM_PHRASE.match(m["text"]):
            return replace(line, kind="system", channel="system", speaker=m["name"], text=text)
        return replace(line, kind="message", speaker=m["name"], text=m["text"].strip())
    if _SYSTEM_PLAIN.match(text):
        return replace(line, kind="system", channel="system")
    return line


def _union(a: Region, b: Region) -> Region:
    x0, y0 = min(a.x, b.x), min(a.y, b.y)
    x1, y1 = max(a.x + a.width, b.x + b.width), max(a.y + a.height, b.y + b.height)
    return Region(x0, y0, x1 - x0, y1 - y0)


def parse(ocr_lines: list[OcrLine]) -> list[ChatLine]:
    """Every OCR line ends up in exactly one ChatLine; nothing is silently dropped."""
    if not ocr_lines:
        return []
    height = statistics.median(line.box.height for line in ocr_lines)
    first = ocr_lines[0]
    # The top line of a scrolled chat is cut in half: no readable start, low confidence.
    top_is_cut = not _starts_line(first.text) and first.confidence < 0.9
    groups: list[list[OcrLine]] = []
    for i, line in enumerate(ocr_lines):
        previous = ocr_lines[i - 1] if i else None
        gap = line.box.y - previous.box.y if previous else 0
        # A wrapped line sits closer to the one above than a new message does, and has no start.
        # (Only the lower half of a cut line is visible, so its wrap sits even closer.)
        low = 0 if top_is_cut and len(groups) == 1 else 0.95 * height
        if previous and not _starts_line(line.text) and low <= gap < 1.4 * height:
            groups[-1].append(line)
        else:
            groups.append([line])

    result = []
    for i, group in enumerate(groups):
        text = " ".join(line.text for line in group)
        confidence = min(line.confidence for line in group)
        box = group[0].box
        for line in group[1:]:
            box = _union(box, line.box)
        parsed = replace(_classify(text, confidence, box), head=group[0].box)
        result.append(replace(parsed, kind="cut") if i == 0 and top_is_cut else parsed)
    return result

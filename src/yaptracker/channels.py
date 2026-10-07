"""Team / match / system of a line: from its leading icon first (#173), then its colour (#14).

The text of [Name]: lines can't tell team from match chat. The icon in front can: a small
diamond is match chat, the three-person icon is team chat. That holds on HDR screens too, where
Windows washes match orange and team blue into the same pale yellow. When the icon is hidden
(a bright background behind it), the colour decides. Colours are user settings (team chat is
the "friendly" colour), so they are learned from lines whose channel the text already proves:
comms-wheel lines are team, system lines are system. Calibration saves them.
"""

import re
from dataclasses import dataclass, replace

import cv2
import numpy as np

from yaptracker.capture.source import Region
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import ChatLine

# Hue in degrees. Match orange and system yellow are Overwatch's defaults; team follows the
# friendly colour, which Overwatch ships blue.
DEFAULT_HUES = {"match": 30.0, "system": 56.0, "team": 200.0}
MAX_DISTANCE = 10.0  # degrees; further from every known colour -> leave the channel unknown
SYSTEM_FILL = 0.68  # the round system icon fills ~0.72-0.83 of its box, the diamond ~0.56-0.64
SYSTEM_HOLE = 0.85  # share of the icon's middle that's bright: below it, there's an i inside
ICON_HUE = 30.0  # degrees: blobs this close to the line's text colour are its icon
GROUP_DISTANCE = 20.0  # degrees: a two-people icon in a team- or match-like colour isn't group
_MIN_PIXELS = 50


def text_hue(image: np.ndarray, box: Region) -> float | None:
    """Median hue of the bright, saturated (= text) pixels in the line's box of a BGR image."""
    patch = box.crop(image)
    if patch.size == 0:
        return None
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    text = hsv[(hsv[:, 2] > 150) & (hsv[:, 1] > 90)]
    return float(np.median(text[:, 0]) * 2) if len(text) >= _MIN_PIXELS else None


@dataclass(frozen=True)
class IconStats:
    """The icon left of a line, measured: sizes relative to the text height (#173, #228)."""

    blobs: int  # bright, saturated parts in the line's colour
    width: float
    height: float
    fill: float  # share of the icon's box that's bright
    middle: float  # share of the box's middle ninth that's bright (the system i is dark)


def icon_stats(
    image: np.ndarray, head: Region, hue: float | None = None, strict: bool = False
) -> IconStats | None:
    """Measure the icon left of the text. `hue`: the line's text colour; only blobs in that
    colour count, so bright background next to the icon doesn't look like more people.
    `strict`: nothing in that colour, no icon (otherwise any bright blob still counts)."""
    h = head.height
    x0, x1 = max(0, int(head.x - 1.6 * h)), max(0, int(head.x - 0.1 * h))
    if h <= 0 or x1 - x0 < 0.5 * h:
        return None
    cell = image[max(0, head.y) : head.y + h, x0:x1]
    if cell.size == 0:
        return None
    hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 2] > 170) & (hsv[:, :, 1] > 60)).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    big = [i for i in range(1, count) if stats[i][4] >= max(4, (h / 10) ** 2)]
    if hue is not None:
        own = [
            i
            for i in big
            if hue_distance(float(np.median(hsv[:, :, 0][labels == i]) * 2), hue) <= ICON_HUE
        ]
        big = own if strict else own or big  # never all: a washed-out icon still counts
    if not big:
        return None
    blobs = [stats[i] for i in big]
    left, top = min(s[0] for s in blobs), min(s[1] for s in blobs)
    right, bottom = max(s[0] + s[2] for s in blobs), max(s[1] + s[3] for s in blobs)
    bw, bh = right - left, bottom - top
    middle = mask[top + bh // 3 : top + 2 * bh // 3 + 1, left + bw // 3 : left + 2 * bw // 3 + 1]
    return IconStats(len(blobs), bw / h, bh / h, sum(int(s[4]) for s in blobs) / max(1, bw * bh),
                     float(middle.mean()) if middle.size else 1.0)  # fmt: skip


def classify_icon(icon: IconStats | None) -> str | None:
    """ "match" (diamond), "system" (round i), "team" (three people), "group" (two people),
    "people" (people, too blurred to count), None (hidden or something else).

    Measured on Marv's 1440p and 4K HDR frames and Void's 1080p ones (#173, #228), biggest
    first: team ~6 blobs, 0.8-1.0 of the text height wide and wider than high; group 3-4 blobs,
    0.6-0.75; the system disc and the diamond one blob each, 0.3-0.6. The disc is full (fill
    ~0.72-0.83) but for the dark i in its middle; the diamond fills ~0.56-0.64 and has no hole,
    which keeps a blurred diamond on a bright background from looking like a disc."""
    if icon is None:
        return None
    w, h = icon.width, icon.height
    if icon.blobs == 1 and 0.2 <= w <= 0.6 and 0.2 <= h <= 0.6:
        if abs(w - h) > 0.12:
            return None
        return "system" if icon.fill >= SYSTEM_FILL and icon.middle < SYSTEM_HOLE else "match"
    if 0.5 <= h <= 0.92:
        if icon.blobs >= 5 and 0.75 <= w <= 1.1 and w / h >= 1.1:
            return "team"
        if 3 <= icon.blobs <= 4 and 0.5 <= w < 0.8:
            return "group"
        if 0.6 <= w <= 1.1:
            return "people"
    return None


def has_icon(image: np.ndarray, box: Region) -> bool:
    """A channel icon in the row's own colour left of its text (#329): that row starts a new
    line, it's never a wrapped continuation. Strict, so a bright map behind a wrap isn't one."""
    hue = text_hue(image, box)
    return hue is not None and icon_stats(image, box, hue, strict=True) is not None


def icon_shape(image: np.ndarray, head: Region, hue: float | None = None) -> str | None:
    """The channel the icon left of the text shows (see classify_icon)."""
    return classify_icon(icon_stats(image, head, hue))


TEAM_DISTANCE = 30.0  # degrees: a people icon this close to the team colour is team chat


GLUED_DISTANCE = 30.0  # degrees: a trailing word this far from the line's colour is background


def cut_glued(lines: list[OcrLine], image: np.ndarray, known: dict[str, float] | None = None,
              hue=text_hue) -> list[OcrLine]:  # fmt: skip
    """Background text glued to the end of a line on a bright frame ("gg 512", "boy 型 2325",
    #172) is cut: trailing words whose colour is far from the line's first word (the name is
    there) and from every chat colour. The first word always stays."""
    chat = list((known or {}).values())
    result = []
    for line in lines:
        keep = list(line.parts)
        own = hue(image, keep[0][1]) if keep else None
        refs = ([own] if own is not None else []) + chat
        while len(keep) > 1 and refs:
            last = hue(image, keep[-1][1])
            if last is None or any(hue_distance(last, ref) <= GLUED_DISTANCE for ref in refs):
                break
            keep.pop()
        if len(keep) == len(line.parts):
            result.append(line)
            continue
        x0, y0 = min(b.x for _, b in keep), min(b.y for _, b in keep)
        x1 = max(b.x + b.width for _, b in keep)
        y1 = max(b.y + b.height for _, b in keep)
        result.append(replace(line, text=" ".join(t for t, _ in keep), parts=tuple(keep),
                              box=Region(x0, y0, x1 - x0, y1 - y0)))  # fmt: skip
    return result


def hue_distance(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


_GROUP_SYSTEM = re.compile(r"\S+'s group wants to stay as a team")  # shown in group colour
_PROMPT = re.compile(r"^\[(Team|Match|Group)\]")  # the open chat box, in its channel's colour


def learn(lines: list[ChatLine], image: np.ndarray) -> dict[str, float]:
    """Colours this frame proves: comms lines are team, system lines are system, typed lines
    with a clear icon are what the icon says (#173), and the open chat box's "[Group]" prompt
    and "...'s group wants to stay as a team" are the group colour (#80)."""
    samples: dict[str, list[float]] = {}
    for line in lines:
        channel = {"comms": "team", "system": "system"}.get(line.kind)
        if line.kind == "system" and _GROUP_SYSTEM.match(line.text):
            channel = "group"
        if line.kind == "input" and (prompt := _PROMPT.match(line.text)):
            channel = prompt[1].lower()
        hue = text_hue(image, line.box)
        if line.kind == "message":
            shape = icon_shape(image, line.head or line.box, hue)
            channel = shape if shape in ("match", "team") else None  # group: by colour (#80)
        if channel and hue is not None:
            samples.setdefault(channel, []).append(hue)
    return {channel: float(np.median(hues)) for channel, hues in samples.items()}


def _group_colour(hue: float | None, learned: dict[str, float]) -> bool:
    """A two-people icon is group chat if its colour isn't the team's or match's (#228)."""
    if hue is None:
        return False
    if "group" in learned:
        return hue_distance(hue, learned["group"]) <= TEAM_DISTANCE
    # not team's, not match's, and not system yellow: on HDR every channel turns that yellow
    others = [learned.get("team"), learned.get("match", DEFAULT_HUES["match"]),
              DEFAULT_HUES["system"]]  # fmt: skip
    return all(ref is None or hue_distance(hue, ref) > GROUP_DISTANCE for ref in others)


def assign(
    lines: list[ChatLine], image: np.ndarray, known: dict[str, float] | None = None
) -> list[ChatLine]:
    """Fill in the channel of typed [Name]: lines. Unsure stays unknown (text-only result)."""
    learned = {**(known or {}), **learn(lines, image)}
    hues = {**DEFAULT_HUES, **learned}
    result = []
    for line in lines:
        hue = text_hue(image, line.box) if line.kind == "message" else None
        shape = icon_shape(image, line.head or line.box, hue) if line.kind == "message" else None
        if shape == "group" and not _group_colour(hue, learned):
            shape = "people"  # colour only confirms: on HDR every channel is the same yellow
        if shape == "system" and (hue is None or hue_distance(hue, DEFAULT_HUES["system"]) > 20):
            shape = None  # system is always yellow (#228)
        if shape in ("match", "team", "group"):
            result.append(replace(line, channel=shape))
            continue
        if shape == "system":  # "[Name] was invited to the group.": a phrase the list lacks
            text = f"[{line.speaker}] {line.text}" if line.speaker else line.text
            result.append(replace(line, kind="system", channel="system", text=text))
            continue
        # A people icon is a team icon blurred by the background, or the group icon: team only
        # in team colours. Group chat needs its own colour first (#80), so it stays unknown here.
        if (shape == "people" and hue is not None and "team" in learned
                and hue_distance(hue, learned["team"]) <= TEAM_DISTANCE):  # fmt: skip
            result.append(replace(line, channel="team"))
            continue
        if hue is not None:
            channel, distance = min(((c, hue_distance(hue, h)) for c, h in hues.items()),
                                    key=lambda item: item[1])  # fmt: skip
            # A typed line can be team or match (or group), never a system line.
            if distance <= MAX_DISTANCE and channel != "system":
                line = replace(line, channel=channel)
        result.append(line)
    return result

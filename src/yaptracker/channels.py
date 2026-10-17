"""Team / match / system of a line: from its leading icon first (#173), then its colour (#14).

The text of [Name]: lines can't tell team from match chat. The icon in front can: a small
diamond is match chat, the three-person icon is team chat. That holds on HDR screens too, where
Windows washes match orange and team blue into the same pale yellow. On a bright background the
icon is found by how it stands out from it (#403); when it's still hidden, the colour decides,
but only when it's clearly one channel's. Colours are user settings (team chat is the
"friendly" colour), so they are learned from lines whose channel the text already proves:
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


ICON_COLOUR = 50  # 0-255 per colour channel: blobs this close to the biggest one's colour
CONTRAST = 60  # how much (0-255, any colour channel) the icon stands out from what's around it
BRIGHT_TEAM_FILL, BRIGHT_TEAM_MIDDLE = 0.35, 0.6  # three people with the middle one in front


def icon_on_background(image: np.ndarray, head: Region) -> IconStats | None:
    """The icon in front of a bright background (#403): there everything is as bright and as
    coloured as the icon, so icon_stats sees one big blob. The icon is what stands out from the
    background around it (a median much wider than the icon); its dark rim keeps it apart."""
    h = head.height
    x0, x1 = max(0, int(head.x - 1.6 * h)), max(0, int(head.x - 0.1 * h))
    if h <= 0 or x1 - x0 < 0.5 * h:
        return None
    m = int(0.6 * h)  # room around the cell, for the background
    top, left = max(0, head.y - m), max(0, x0 - m)
    around = image[top : head.y + h + m, left:x1]
    if min(around.shape[:2]) < 3:
        return None
    k = max(3, min(int(1.2 * h), min(around.shape[:2]) - 1) | 1)
    background = cv2.merge([cv2.medianBlur(np.ascontiguousarray(c), k) for c in cv2.split(around)])
    stands_out = cv2.absdiff(around, background).max(axis=2) > CONTRAST
    mask = (stands_out & (around.max(axis=2) > 150)).astype(np.uint8)
    cell = mask[head.y - top : head.y - top + h, x0 - left :]
    count, labels, stats, _ = cv2.connectedComponentsWithStats(np.ascontiguousarray(cell))
    size, text_x = max(4, (h / 10) ** 2), head.x - x0
    found = [i for i in range(1, count)
             if stats[i][4] >= size and _in_icon_spot(stats[i], h, text_x)]  # fmt: skip
    if not found:
        return None
    # The icon is one colour: bits of the map in other colours next to it aren't part of it.
    colours = around[head.y - top : head.y - top + h, x0 - left :]
    mean = {i: colours[labels == i].mean(axis=0) for i in found}
    biggest = mean[max(found, key=lambda i: stats[i][4])]
    blobs = [stats[i] for i in found if np.abs(mean[i] - biggest).max() <= ICON_COLOUR]
    x, y = min(s[0] for s in blobs), min(s[1] for s in blobs)
    bw, bh = max(s[0] + s[2] for s in blobs) - x, max(s[1] + s[3] for s in blobs) - y
    middle = cell[y + bh // 3 : y + 2 * bh // 3 + 1, x + bw // 3 : x + 2 * bw // 3 + 1]
    return IconStats(len(blobs), bw / h, bh / h, sum(int(s[4]) for s in blobs) / max(1, bw * bh),
                     float(middle.mean()) if middle.size else 1.0)  # fmt: skip


def _in_icon_spot(blob: np.ndarray, h: int, text_x: float) -> bool:
    """A blob centred where the icon sits: measured on 3,500 clear icons of Marv's samples, the
    middle of the icon is 0.73-1.33 text heights left of the text and half-way down (#403), and
    the team icon is 0.9 wide. Bits of the map above, below or right next to the text aren't."""
    x, y = blob[0] + blob[2] / 2, blob[1] + blob[3] / 2
    return x - text_x <= -0.35 * h and 0.1 * h <= y <= 0.85 * h


def classify_on_background(icon: IconStats | None) -> str | None:
    """Only the sure ones from a bright background: the diamond, and three people with the
    middle one filled in. A busy background can look like a few blobs (a diamond on camouflage
    came out as "team"), and a wrong channel is worse than none (#403)."""
    shape = classify_icon(icon)
    if shape == "match":
        return shape
    if shape == "team" and icon.fill >= BRIGHT_TEAM_FILL and icon.middle >= BRIGHT_TEAM_MIDDLE:
        return shape
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
    there) and from every chat colour. The first word always stays.

    Text far after the message (a gap over FAR_GAP line heights) that isn't in a chat colour
    is cut too, white or grey included (#497: "gj E:\\data\\shots", a File Explorer window
    over the chat box on screen)."""
    chat = list((known or {}).values())
    result = []
    for line in lines:
        keep = list(line.parts)
        own = hue(image, keep[0][1]) if keep else None
        refs = ([own] if own is not None else []) + chat
        keep = _before_far_text(keep, image, refs, hue)
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


FAR_GAP = 3.0  # line heights of empty space after which other text isn't the message (#497)
_REPORT_LINK = re.compile(r"\[?Report\]?$", re.IGNORECASE)


def _before_far_text(parts: list, image: np.ndarray, refs: list[float], hue) -> list:
    """The words up to a big gap after which the text isn't in the line's or a chat colour.
    Without a colour to compare, nothing goes; Overwatch's own "[Report]" link always stays."""
    if not refs:
        return parts
    for n in range(1, len(parts)):
        (_, before), (_, after) = parts[n - 1], parts[n]
        gap = after.x - (before.x + before.width)
        if gap > FAR_GAP * max(before.height, after.height) and not _REPORT_LINK.match(
                parts[n][0]):  # fmt: skip
            colour = hue(image, after)
            if colour is None or not any(hue_distance(colour, ref) <= GLUED_DISTANCE
                                         for ref in refs):  # fmt: skip
                return parts[:n]
    return parts


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
        if channel and hue is not None and not bright_behind(image, line.head or line.box):
            samples.setdefault(channel, []).append(hue)
    return {channel: float(np.median(hues)) for channel, hues in samples.items()}


BRIGHT_BEHIND = 0.5  # share of bright pixels where the icon sits: the map behind is bright


def bright_behind(image: np.ndarray, head: Region) -> bool:
    """The map behind the line is bright, so its "text colour" is mostly the map's (#403): on a
    blue sky a match line came out blue and taught that as the team colour."""
    h = head.height
    x0, x1 = max(0, int(head.x - 1.6 * h)), max(0, int(head.x - 0.1 * h))
    cell = image[max(0, head.y) : head.y + h, x0:x1]
    return cell.size > 0 and float((cell.max(axis=2) > 150).mean()) >= BRIGHT_BEHIND


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
        if line.kind == "message" and shape in (None, "people"):  # a bright background? (#403)
            sure = classify_on_background(icon_on_background(image, line.head or line.box))
            shape = sure or shape
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
        if hue is not None and bright_behind(image, line.head or line.box):
            hue = None  # the map's colour, not the text's: the icon alone decides (#403)
        if (shape == "people" and hue is not None and "team" in learned
                and _clearly(hue, hues, "team", TEAM_DISTANCE)):  # fmt: skip
            result.append(replace(line, channel="team"))
            continue
        if hue is not None:
            channel = min(hues, key=lambda c: hue_distance(hue, hues[c]))
            # A typed line can be team or match (or group), never a system line.
            if channel != "system" and _clearly(hue, hues, channel, MAX_DISTANCE):
                line = replace(line, channel=channel)
        result.append(line)
    return result


def _clearly(hue: float, hues: dict[str, float], channel: str, within: float) -> bool:
    """The text has this channel's colour: close to it and clearly closer than to any other.
    On HDR, match and team come out the same yellow, and picking the nearer one is a coin
    toss: a wrong channel half the time, worse than none (#403)."""
    mine = hue_distance(hue, hues[channel])
    return mine <= within and all(
        hue_distance(hue, other) - mine >= MAX_DISTANCE for c, other in hues.items() if c != channel
    )

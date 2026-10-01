"""Team / match / system of a line: from its leading icon first (#173), then its colour (#14).

The text of [Name]: lines can't tell team from match chat. The icon in front can: a small
diamond is match chat, the three-person icon is team chat. That holds on HDR screens too, where
Windows washes match orange and team blue into the same pale yellow. When the icon is hidden
(a bright background behind it), the colour decides. Colours are user settings (team chat is
the "friendly" colour), so they are learned from lines whose channel the text already proves:
comms-wheel lines are team, system lines are system. Calibration saves them.
"""

from dataclasses import replace

import cv2
import numpy as np

from yaptracker.capture.source import Region
from yaptracker.parser import ChatLine

# Hue in degrees. Match orange and system yellow are Overwatch's defaults; team follows the
# friendly colour, which Overwatch ships blue.
DEFAULT_HUES = {"match": 30.0, "system": 56.0, "team": 200.0}
MAX_DISTANCE = 10.0  # degrees; further from every known colour -> leave the channel unknown
_MIN_PIXELS = 50


def text_hue(image: np.ndarray, box: Region) -> float | None:
    """Median hue of the bright, saturated (= text) pixels in the line's box of a BGR image."""
    patch = box.crop(image)
    if patch.size == 0:
        return None
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    text = hsv[(hsv[:, 2] > 150) & (hsv[:, 1] > 90)]
    return float(np.median(text[:, 0]) * 2) if len(text) >= _MIN_PIXELS else None


def icon_shape(image: np.ndarray, head: Region) -> str | None:
    """The icon left of the text: "match" (diamond), "team" (three people), "people" (two or
    three people: group chat, or a blurred team icon), None (hidden by the background).

    Sizes are relative to the text height, measured on 1440p and 4K HDR frames (#173): the
    diamond is one blob ~0.25-0.5 of it, square; the team icon ~6 blobs (heads and bodies),
    ~1.1-1.4x as wide as high; the group icon (two people) up to 4 blobs, about square. On a
    bright background the team icon's blobs merge and it looks like the group one."""
    h = head.height
    x0, x1 = max(0, int(head.x - 1.6 * h)), max(0, int(head.x - 0.1 * h))
    if h <= 0 or x1 - x0 < 0.5 * h:
        return None
    cell = image[max(0, head.y) : head.y + h, x0:x1]
    if cell.size == 0:
        return None
    hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 2] > 170) & (hsv[:, :, 1] > 60)).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    blobs = [s for s in stats[1:] if s[4] >= max(4, (h / 10) ** 2)]
    if not blobs:
        return None
    left, top = min(s[0] for s in blobs), min(s[1] for s in blobs)
    width = (max(s[0] + s[2] for s in blobs) - left) / h
    height = (max(s[1] + s[3] for s in blobs) - top) / h
    if len(blobs) == 1 and 0.2 <= width <= 0.55 and 0.2 <= height <= 0.55:
        return "match" if abs(width - height) <= 0.12 else None
    if 0.65 <= width <= 1.1 and 0.55 <= height <= 0.92:
        return "team" if len(blobs) >= 5 and width / height >= 1.1 else "people"
    return None


TEAM_DISTANCE = 30.0  # degrees: a people icon this close to the team colour is team chat


def _distance(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def learn(lines: list[ChatLine], image: np.ndarray) -> dict[str, float]:
    """Colours this frame proves: comms lines are team, system lines are system, and typed lines
    with a clear icon are what the icon says (#173)."""
    samples: dict[str, list[float]] = {}
    for line in lines:
        channel = {"comms": "team", "system": "system"}.get(line.kind)
        if line.kind == "message":
            shape = icon_shape(image, line.head or line.box)
            channel = shape if shape in ("match", "team") else None
        if channel and (hue := text_hue(image, line.box)) is not None:
            samples.setdefault(channel, []).append(hue)
    return {channel: float(np.median(hues)) for channel, hues in samples.items()}


def assign(
    lines: list[ChatLine], image: np.ndarray, known: dict[str, float] | None = None
) -> list[ChatLine]:
    """Fill in the channel of typed [Name]: lines. Unsure stays unknown (text-only result)."""
    learned = {**(known or {}), **learn(lines, image)}
    hues = {**DEFAULT_HUES, **learned}
    result = []
    for line in lines:
        shape = icon_shape(image, line.head or line.box) if line.kind == "message" else None
        if shape in ("match", "team"):
            result.append(replace(line, channel=shape))
            continue
        hue = text_hue(image, line.box) if line.kind == "message" else None
        # A people icon is a team icon blurred by the background, or the group icon: team only
        # in team colours. Group chat needs its own colour first (#80), so it stays unknown here.
        if (shape == "people" and hue is not None and "team" in learned
                and _distance(hue, learned["team"]) <= TEAM_DISTANCE):  # fmt: skip
            result.append(replace(line, channel="team"))
            continue
        if hue is not None:
            channel, distance = min(((c, _distance(hue, h)) for c, h in hues.items()),
                                    key=lambda item: item[1])  # fmt: skip
            # A typed line can be team or match (or group), never a system line.
            if distance <= MAX_DISTANCE and channel != "system":
                line = replace(line, channel=channel)
        result.append(line)
    return result

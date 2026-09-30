"""Team / match / system from the text colour of a line (#14).

The text of [Name]: lines can't tell team from match chat, but the colour can. Colours are user
settings (team chat is the "friendly" colour), so they are learned from lines whose channel the
text already proves: comms-wheel lines are team, system lines are system. Calibration saves them.
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


def _distance(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def learn(lines: list[ChatLine], image: np.ndarray) -> dict[str, float]:
    """Colours this frame proves: comms lines are team, system lines are system."""
    samples: dict[str, list[float]] = {}
    for line in lines:
        channel = {"comms": "team", "system": "system"}.get(line.kind)
        if channel and (hue := text_hue(image, line.box)) is not None:
            samples.setdefault(channel, []).append(hue)
    return {channel: float(np.median(hues)) for channel, hues in samples.items()}


def assign(
    lines: list[ChatLine], image: np.ndarray, known: dict[str, float] | None = None
) -> list[ChatLine]:
    """Fill in the channel of typed [Name]: lines. Unsure stays unknown (text-only result)."""
    hues = {**DEFAULT_HUES, **(known or {}), **learn(lines, image)}
    result = []
    for line in lines:
        hue = text_hue(image, line.box) if line.kind == "message" else None
        if hue is not None:
            channel, distance = min(((c, _distance(hue, h)) for c, h in hues.items()),
                                    key=lambda item: item[1])  # fmt: skip
            # A typed line can be team or match (or group), never a system line.
            if distance <= MAX_DISTANCE and channel != "system":
                line = replace(line, channel=channel)
        result.append(line)
    return result

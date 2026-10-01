"""Fake data for `--dev` review in a browser. Made-up names only - the repo is public."""

import threading
import time
from collections.abc import Iterator

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from yaptracker.capture.source import Frame, default_chat_region

ENABLED = False  # set by `python -m yaptracker --dev`

_LINES = [
    ((255, 174, 77), "[NoodleBonk]: WAHOOOO"),
    ((255, 174, 77), "[tortillaTank]: not the wahoo guy again lmao"),
    ((124, 227, 139), "SirPeelsALot (Reinhardt): Group up!"),
    ((124, 227, 139), "[Bapricot]: drop the lamp on me pls"),
    ((255, 214, 90), "[gremlin.exe] started playing Overwatch."),
    ((255, 174, 77), "[NoodleBonk]: it is literally the first fight"),
]


def screenshot(width: int = 2560, height: int = 1440) -> Image.Image:
    """A stand-in for an Overwatch screenshot: sky gradient plus chat lines in the usual spot."""
    top, bottom = (43, 61, 85), (107, 90, 42)
    gradient = Image.linear_gradient("L").resize((width, height))
    channels = [
        gradient.point(lambda v, a=a, b=b: a + (b - a) * v // 255)
        for a, b in zip(top, bottom, strict=True)
    ]
    img = Image.merge("RGB", channels)
    draw = ImageDraw.Draw(img)
    region = default_chat_region(width, height)
    font = ImageFont.load_default(size=round(height / 52))
    y = region.y + region.height - len(_LINES) * font.size * 1.6
    for colour, text in _LINES:
        draw.text((region.x + 20, y), text, fill=colour, font=font, stroke_width=2, stroke_fill=0)
        y += font.size * 1.6
    return img


class DemoFrameSource:
    """Stands in for the game in --dev: the demo chat box, 4 times a second."""

    def __init__(self, fps: float = 4.0) -> None:
        self._interval = 1 / fps
        self._closed = threading.Event()
        image = screenshot()
        r = default_chat_region(image.width, image.height)
        crop = image.crop((r.x, r.y, r.x + r.width, r.y + r.height))
        self._chat = np.ascontiguousarray(np.asarray(crop)[:, :, ::-1])

    def frames(self) -> Iterator[Frame]:
        start = time.monotonic()
        while not self._closed.wait(self._interval):
            yield Frame(time.monotonic() - start, self._chat)

    def snapshot(self, timeout: float = 2.0) -> np.ndarray:
        """The whole demo "game window", like WGC's snapshot (#112)."""
        return np.ascontiguousarray(np.asarray(screenshot())[:, :, ::-1])

    def close(self) -> None:
        self._closed.set()

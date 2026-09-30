"""What every frame source delivers to the pipeline."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class Region:
    """A rectangle in window pixels, e.g. the chat box."""

    x: int
    y: int
    width: int
    height: int

    def crop(self, image: np.ndarray) -> np.ndarray:
        return image[self.y : self.y + self.height, self.x : self.x + self.width]


# Measured on real 2560x1440 screenshots (#10). Same spot in hero select, in game and end screens.
_CHAT_1440P = Region(55, 510, 615, 395)


def default_chat_region(width: int, height: int) -> Region:
    """The usual chat box for a 16:9 window of this size, scaled from 2560x1440."""
    sx, sy = width / 2560, height / 1440
    r = _CHAT_1440P
    return Region(round(r.x * sx), round(r.y * sy), round(r.width * sx), round(r.height * sy))


@dataclass(frozen=True)
class Frame:
    ts: float  # seconds since the source started
    image: np.ndarray  # height x width x 3, uint8, BGR (what OCR and WGC capture use)


class FrameSource(Protocol):
    """Yields frames of the chat region in time order. Live capture (WGC) and replay both fit."""

    def frames(self) -> Iterator[Frame]: ...

    def close(self) -> None: ...

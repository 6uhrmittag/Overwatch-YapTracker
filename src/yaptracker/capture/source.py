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


@dataclass(frozen=True)
class RelativeRegion:
    """A rectangle as fractions of the window size, so it survives resolution changes (#84)."""

    x: float
    y: float
    width: float
    height: float

    def to_pixels(self, width: int, height: int) -> Region:
        return Region(round(self.x * width), round(self.y * height),
                      round(self.width * width), round(self.height * height))  # fmt: skip

    @classmethod
    def from_pixels(cls, region: Region, width: int, height: int) -> "RelativeRegion":
        return cls(
            region.x / width, region.y / height, region.width / width, region.height / height
        )


# Measured on real 2560x1440 screenshots (#10). Same spot in hero select, in game and end screens.
DEFAULT_CHAT_BOX = RelativeRegion.from_pixels(Region(55, 510, 615, 395), 2560, 1440)


def default_chat_region(width: int, height: int) -> Region:
    """The usual chat box for a window of this size (measured at 16:9; others scaled for now)."""
    return DEFAULT_CHAT_BOX.to_pixels(width, height)


@dataclass(frozen=True)
class Frame:
    ts: float  # seconds since the source started
    image: np.ndarray  # height x width x 3, uint8, BGR (what OCR and WGC capture use)


class FrameSource(Protocol):
    """Yields frames of the chat region in time order. Live capture (WGC) and replay both fit."""

    def frames(self) -> Iterator[Frame]: ...

    def close(self) -> None: ...

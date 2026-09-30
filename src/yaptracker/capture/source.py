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
class Frame:
    ts: float  # seconds since the source started
    image: np.ndarray  # height x width x 3, uint8, BGR (what OCR and WGC capture use)


class FrameSource(Protocol):
    """Yields frames of the chat region in time order. Live capture (WGC) and replay both fit."""

    def frames(self) -> Iterator[Frame]: ...

    def close(self) -> None: ...

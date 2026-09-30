"""Replay a folder of images as if they came from the game.

python -m yaptracker.capture.replay FOLDER [--fps 4] [--realtime] [--region X Y W H]
"""

import argparse
import re
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
from PIL import Image

from yaptracker.capture.source import Frame, Region

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp"}
# Frames written by tools/extract_frames.py are named by their timestamp in ms, e.g. 012250.png.
_MS_NAME = re.compile(r"\d+")


class ReplayFrameSource:
    """Images from a folder, in file-name order.

    Timestamps come from the file names when all of them are milliseconds (real timing of an
    extracted recording), otherwise frames are spaced 1/fps apart.
    """

    def __init__(
        self,
        folder: Path,
        *,
        fps: float = 4.0,
        region: Region | None = None,
        realtime: bool = False,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.paths = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
        if not self.paths:
            raise FileNotFoundError(f"No images in {folder}")
        self.region = region
        self.realtime = realtime
        self._clock = clock
        self._sleep = sleep
        if all(_MS_NAME.fullmatch(p.stem) for p in self.paths):
            self.timestamps = [int(p.stem) / 1000 for p in self.paths]
        else:
            self.timestamps = [i / fps for i in range(len(self.paths))]

    def frames(self) -> Iterator[Frame]:
        start = self._clock()
        first_ts = self.timestamps[0]
        for path, ts in zip(self.paths, self.timestamps, strict=True):
            ts -= first_ts
            if self.realtime:
                wait = start + ts - self._clock()
                if wait > 0:
                    self._sleep(wait)
            yield Frame(ts=ts, image=self._load(path))

    def close(self) -> None:
        pass

    def _load(self, path: Path) -> np.ndarray:
        with Image.open(path) as img:
            rgb = np.asarray(img.convert("RGB"))
        bgr = np.ascontiguousarray(rgb[:, :, ::-1])
        return self.region.crop(bgr) if self.region else bgr


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--fps", type=float, default=4.0, help="spacing when names aren't ms")
    parser.add_argument("--realtime", action="store_true", help="wait like a live capture would")
    parser.add_argument("--region", type=int, nargs=4, metavar=("X", "Y", "W", "H"))
    args = parser.parse_args(argv)
    region = Region(*args.region) if args.region else None
    source = ReplayFrameSource(args.folder, fps=args.fps, region=region, realtime=args.realtime)
    # Pipeline stub until change detection and OCR exist: show what would be fed in.
    for frame in source.frames():
        height, width = frame.image.shape[:2]
        print(f"{frame.ts:8.3f}s  {width}x{height}")
    source.close()


if __name__ == "__main__":
    main()

"""Does the overlay FPS reader (#212) read real screens? Private data, run by hand.

    python tools/fps_check.py

Reads the FPS box in fixtures/private/screenshots/ (values read by eye below) and in every full
frame of fixtures/private/frames/*/full/ (1440p), the frames also scaled up to 4K. Prints what
was read, the misses, 1440p vs 4K disagreements and the CPU per read. Writes
fixtures/private/fps-check.png: a random sample of boxes with their reading, to check by eye.
Heavy: real OCR on thousands of frames. Run it when nobody is playing.
"""

import random
import time
from pathlib import Path

import cv2
import numpy as np

from yaptracker.game_fps import fps_box, overlay_regions, parse_fps
from yaptracker.ocr.engine import RapidOcrEngine

PRIVATE = Path(__file__).resolve().parents[1] / "fixtures" / "private"
# Read by eye from the overlay in each screenshot (by its number), 2560x1440.
SCREENSHOTS = {"01": None, "02": 150, "03": 181, "04": 180, "05": 140, "06": 190, "07": 151,
               "08": 170, "09": 154, "10": 157, "11": None, "12": None, "13": 170, "14": 153,
               "15": None, "16": 59, "17": None, "18": 184, "19": 170, "20": 166, "21": 175,
               "22": 177, "23": 160}  # fmt: skip  # None: a menu, the overlay sits lower


def main() -> None:
    engine = RapidOcrEngine()
    spent, reads = 0.0, 0

    def read(image: np.ndarray) -> tuple[int | None, np.ndarray | None]:
        nonlocal spent, reads
        height, width = image.shape[:2]
        started = time.process_time()
        box = fps_box(overlay_regions(width, height)["fps"].crop(image), height)
        value = parse_fps(engine.read_line(box)) if box is not None else None
        spent += time.process_time() - started
        reads += box is not None
        return value, box

    for path in sorted((PRIVATE / "screenshots").glob("*.png")):
        value, _ = read(cv2.imread(str(path)))
        if value != SCREENSHOTS[path.name[:2]]:
            print(f"screenshot {path.name}: read {value}, expected {SCREENSHOTS[path.name[:2]]}")
    frames = sorted(PRIVATE.glob("frames/*/full/*.jpg"))
    sample, read_1440 = [], 0
    for path in frames:
        image = cv2.imread(str(path))
        value, box = read(image)
        if value is None:
            print(f"frame {path.relative_to(PRIVATE)}: nothing read")
            continue
        read_1440 += 1
        sample.append((value, box))
        value_4k, _ = read(cv2.resize(image, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC))
        if value_4k != value:
            print(f"frame {path.relative_to(PRIVATE)}: {value} at 1440p, {value_4k} at 4K")
    print(f"{len(SCREENSHOTS)} screenshots, {len(frames)} frames: {read_1440} read; "
          f"{1000 * spent / max(1, reads):.1f} ms CPU per read")  # fmt: skip
    tiles = []
    for value, box in random.Random(212).sample(sample, min(48, len(sample))):
        tile = np.zeros((50, 300, 3), np.uint8)
        tile[: box.shape[0] * 2, : box.shape[1] * 2] = cv2.resize(box, None, fx=2, fy=2)
        cv2.putText(tile, str(value), (200, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        tiles.append(tile)
    if tiles:
        rows = [np.hstack(tiles[i : i + 4]) for i in range(0, len(tiles) - len(tiles) % 4, 4)]
        cv2.imwrite(str(PRIVATE / "fps-check.png"), np.vstack(rows))


if __name__ == "__main__":
    main()

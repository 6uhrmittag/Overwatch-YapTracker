"""One fresh RapidOCR read of every gold picture (#608): the like-for-like baseline and its cost.

    python tools/ocr_train/reread_rapid.py

The stored text is the best of several live readings of a whole chat box; a re-read engine gets
one look at the row picture. This gives RapidOCR the same one look, as the app reads a 4K frame
(scale 4/3), on one thread, and writes readings/rapid.jsonl for score.py. Prints ms per row.
"""

import json
import statistics
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
import score  # noqa: E402

from yaptracker.ocr.engine import RapidOcrEngine  # noqa: E402

SCALE_4K = 4 / 3  # what the app uses for a 2160-high window (#169)


def main() -> None:
    private = common.private()
    if common.game_running():
        sys.exit("Overwatch is running: no timed pass now")
    cv2.setNumThreads(1)
    engine = RapidOcrEngine()
    gold = score.load(private)
    (private / "readings").mkdir(exist_ok=True)
    times = []
    with (private / "readings" / "rapid.jsonl").open("w", encoding="utf-8") as out:
        for g in gold:
            image = cv2.imread(str(private / g["picture"]))
            start = time.perf_counter()
            lines = engine.read(image, scale=SCALE_4K)
            times.append((time.perf_counter() - start) * 1000)
            row = " ".join(line.text for line in lines)
            out.write(json.dumps({"id": g["id"], "row": row}, ensure_ascii=False) + "\n")
    print(f"{len(gold)} rows: median {statistics.median(times):.0f} ms, "
          f"mean {statistics.mean(times):.0f} ms per row")  # fmt: skip


if __name__ == "__main__":
    main()

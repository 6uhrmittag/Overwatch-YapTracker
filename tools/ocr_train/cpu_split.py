"""Phase 3 of the OCR POC (#608): where the CPU of one 4K chat read goes.

    python tools/ocr_train/cpu_split.py

Reads the newest full chat-box samples the app collected (data/debug/<day>/*-chat/*.png) the
way the app does (4K scale, one thread) and adds up RapidOCR's own timers: detection, the
direction check (cls) and recognition, plus the second (Latin) read when a line looks German.
A new recognizer can only save what recognition costs.
"""

import statistics
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
from reread_rapid import SCALE_4K  # noqa: E402

from yaptracker.ocr.engine import RapidOcrEngine  # noqa: E402

FRAMES = 80
HEIGHT_4K = 500  # a 4K chat box is higher than this; smaller samples are another resolution


def main() -> None:
    if common.game_running():
        sys.exit("Overwatch is running: no timed pass now")
    cv2.setNumThreads(1)
    engine = RapidOcrEngine()
    frames = []
    for path in sorted((common.DATA / "debug").glob("*/*-chat/*.png"), reverse=True):
        image = cv2.imread(str(path))
        if image is not None and image.shape[0] >= HEIGHT_4K:
            frames.append(image)
        if len(frames) == FRAMES:
            break
    parts, totals, lines = {"det": [], "cls": [], "rec": []}, [], []
    for image in frames:
        big = cv2.resize(image, None, fx=SCALE_4K, fy=SCALE_4K, interpolation=cv2.INTER_CUBIC)
        start = time.perf_counter()
        result, elapse = engine._ocr(big)
        totals.append((time.perf_counter() - start) * 1000)
        if not elapse:
            continue
        for name, seconds in zip(parts, elapse, strict=True):
            parts[name].append(seconds * 1000)
        lines.append(len(result or []))
    size = f"{frames[0].shape[1]}x{frames[0].shape[0]}" if frames else "-"
    print(f"{len(frames)} chat boxes ({size}), median {statistics.median(lines):.0f} text boxes")
    whole = statistics.mean(totals)
    print(f"whole read: mean {whole:.0f} ms, median {statistics.median(totals):.0f} ms")
    for name, values in parts.items():
        mean = sum(values) / len(totals)
        print(f"  {name}: mean {mean:6.1f} ms  ({mean / whole:.0%})")
    print(f"  second (Latin) reads: {engine._ocr.text_rec.latin_reads} of {len(frames)} boxes")


if __name__ == "__main__":
    main()

"""Phase 3 of the OCR POC (#608): where the CPU of one 4K chat read goes.

    python tools/ocr_train/cpu_split.py ours=train/ours

Reads the newest full chat-box samples the app collected (data/debug/<day>/*-chat/*.png) the
way the app does (4K scale, one thread) and adds up RapidOCR's own timers: detection, the
direction check (cls) and recognition, plus the second (Latin) read when a line looks German.
A new recognizer can only save what recognition costs.
"""

import argparse
import statistics
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent))
import bench  # noqa: E402
import common  # noqa: E402
from reread_rapid import SCALE_4K  # noqa: E402

FRAMES = 80
HEIGHT_4K = 500  # a 4K chat box is higher than this; smaller samples are another resolution


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args.add_argument("models", nargs="*", help="name=folder with rec.onnx and dict.txt")
    opts = args.parse_args()
    common.no_game()
    cv2.setNumThreads(1)
    frames = []
    for path in sorted((common.DATA / "debug").glob("*/*-chat/*.png"), reverse=True):
        image = cv2.imread(str(path))
        if image is not None and image.shape[0] >= HEIGHT_4K:
            frames.append(image)
        if len(frames) == FRAMES:
            break
    if not frames:
        sys.exit(f"no 4K chat-box samples under {common.DATA / 'debug'}: nothing to time")
    size = f"{frames[0].shape[1]}x{frames[0].shape[0]}"
    print(f"{len(frames)} chat boxes ({size})")
    for name, engine in bench.engines(common.private(), opts.models).items():
        parts, totals, boxes = {"det": [], "cls": [], "rec": []}, [], []
        for image in frames:
            big = cv2.resize(image, None, fx=SCALE_4K, fy=SCALE_4K, interpolation=cv2.INTER_CUBIC)
            start = time.perf_counter()
            result, elapse = engine._ocr(big)
            totals.append((time.perf_counter() - start) * 1000)
            boxes.append(len(result or []))
            for part, seconds in zip(parts, elapse or [], strict=False):
                parts[part].append(seconds * 1000)
        whole = statistics.mean(totals)
        print(f"\n{name}: whole read mean {whole:.0f} ms, median {statistics.median(totals):.0f}"
              f" ms, {statistics.median(boxes):.0f} text boxes (median)")  # fmt: skip
        for part, values in parts.items():
            mean = sum(values) / len(totals)
            print(f"  {part}: mean {mean:6.1f} ms  ({mean / whole:.0%})")
        few = [t for t, n in zip(totals, boxes, strict=True) if n <= 4]
        if few:
            print(f"  boxes with 4 lines or fewer ({len(few)}): mean {statistics.mean(few):.0f} ms")


if __name__ == "__main__":
    main()

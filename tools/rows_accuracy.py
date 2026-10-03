"""Do chat reads without text detection read as well? (#249) Private data, run by hand.

    python tools/rows_accuracy.py

Scores RapidOCR's read() (detection + recognition) and read_rows() (the text mask's rows,
recognition only, with two vertical paddings) on the English set (fixtures/private/ocr-spike,
#11) and the German one (fixtures/private/ocr-german, #118) with tools/ocr_spike.py's scoring.
Then CPU per read on the 4K HDR debug samples of 2026-10-01/02, and how often both agree.
Prints aggregates only.
"""

import importlib.util
import json
import time
from pathlib import Path

import cv2

from yaptracker.ocr.engine import RapidOcrEngine

PRIVATE = Path(__file__).resolve().parents[1] / "fixtures" / "private"
_spec = importlib.util.spec_from_file_location("ocr_spike", Path(__file__).parent / "ocr_spike.py")
spike = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spike)


def rows(engine, image, pad_y: float):
    from yaptracker.ocr import engine as ocr

    ocr.PAD_Y = pad_y
    return engine.read_rows(image, image.shape[0] / 395)


def main() -> None:
    engine = RapidOcrEngine()
    ways = {"read": lambda image: engine.read(image),
            "rows0": lambda image: rows(engine, image, 0.0),
            "rows15": lambda image: rows(engine, image, 0.15)}  # fmt: skip
    for name in ("ocr-spike", "ocr-german"):
        truth = json.loads((PRIVATE / name / "truth.json").read_text(encoding="utf-8"))
        for way, read in ways.items():
            got, fallback = {}, 0
            for crop in truth:
                image = cv2.imread(str(PRIVATE / name / "crops" / crop))
                started = time.process_time()
                lines = read(image)
                if lines is None:
                    fallback += 1
                    lines = engine.read(image)
                got[crop] = ([line.text for line in lines], 1000 * (time.process_time() - started))
            s = spike.score(truth, got)
            ms = sum(v[1] for v in got.values()) / len(got)
            chars, exact = s["char"], s["exact_lines"]
            print(f"{name:10} {way:6} chars {chars:.3f}  no-space {s['char_nospace']:.3f}  "
                  f"exact {exact:.2f}  names {s['names']:.2f}  {ms:.0f} ms/crop  "
                  f"fallback {fallback}/{len(truth)}", flush=True)  # fmt: skip
    debug = Path("/mnt/c/Users/marvi/AppData/Local/YapTracker/data/debug")
    frames = sorted(p for day in ("2026-10-01", "2026-10-02")
                    for p in debug.glob(f"{day}/*-chat/*.png"))[:80]  # fmt: skip
    if not frames:
        return
    spent = {"read": 0.0, "rows0": 0.0}
    same = total = fallback = 0
    for path in frames:
        image = cv2.imread(str(path))
        text_scale = 1.5  # Marv's 4K window
        started = time.process_time()
        a = [line.text for line in engine.read(image, scale=4 / 3)]
        spent["read"] += time.process_time() - started
        started = time.process_time()
        from yaptracker.ocr import engine as ocr

        ocr.PAD_Y = 0.0
        b = engine.read_rows(image, text_scale, scale=4 / 3)
        if b is None:
            fallback += 1
            b = engine.read(image, scale=4 / 3)
        spent["rows0"] += time.process_time() - started
        b = [line.text for line in b]
        total += len(a)
        same += sum(1 for line in a if line in b)
    n = len(frames)
    print(f"4K samples: {n} frames; read {1000 * spent['read'] / n:.0f} ms, rows "
          f"{1000 * spent['rows0'] / n:.0f} ms per read; rows fell back on {fallback}; "
          f"{same}/{total} detected lines read the same")  # fmt: skip


if __name__ == "__main__":
    main()

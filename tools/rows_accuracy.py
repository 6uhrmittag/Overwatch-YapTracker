"""Do chat reads without text detection read as well? (#249) Private data, run by hand.

    python tools/rows_accuracy.py

Scores RapidOCR's read() (detection + recognition) and read_rows() (the text mask's rows,
recognition only) on the English set (fixtures/private/ocr-spike, #11) and the German one
(fixtures/private/ocr-german, #118) with tools/ocr_spike.py's scoring. Prints aggregates only.
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


def main() -> None:
    engine = RapidOcrEngine()
    for name in ("ocr-spike", "ocr-german"):
        truth = json.loads((PRIVATE / name / "truth.json").read_text(encoding="utf-8"))
        results = {"read": {}, "rows": {}}
        fallback = 0
        for crop in truth:
            image = cv2.imread(str(PRIVATE / name / "crops" / crop))
            text_scale = image.shape[0] / 395
            started = time.process_time()
            lines = engine.read(image)
            results["read"][crop] = ([line.text for line in lines],
                                     1000 * (time.process_time() - started))  # fmt: skip
            started = time.process_time()
            rows = engine.read_rows(image, text_scale)
            if rows is None:
                fallback += 1
                rows = engine.read(image)
            results["rows"][crop] = ([line.text for line in rows],
                                     1000 * (time.process_time() - started))  # fmt: skip
        for way, got in results.items():
            s = spike.score(truth, got)
            ms = sum(v[1] for v in got.values()) / len(got)
            chars, exact = s["char"], s["exact_lines"]
            print(f"{name:10} {way:5} chars {chars:.3f}  no-space {s['char_nospace']:.3f}  "
                  f"exact {exact:.2f}  names {s['names']:.2f}  {ms:.0f} ms/crop")  # fmt: skip
        print(f"{name:10} rows fell back to detection on {fallback} of {len(truth)} crops")


if __name__ == "__main__":
    main()

"""Umlauts by picture (#247): accuracy and how often the Latin model runs. Private data.

    python tools/umlaut_check.py

Scores read() on the English set (fixtures/private/ocr-spike, #11) and the German one
(fixtures/private/ocr-german, #118) with tools/ocr_spike.py's scoring, with the picture check
(now) and without it (before), and counts Latin reads on those sets and on Marv's 4K samples of
2026-10-01/02. Prints aggregates only.
"""

import importlib.util
import json
from pathlib import Path

import cv2

from yaptracker.ocr import engine as ocr
from yaptracker.ocr.engine import RapidOcrEngine

PRIVATE = Path(__file__).resolve().parents[1] / "fixtures" / "private"
DEBUG = Path("/mnt/c/Users/marvi/AppData/Local/YapTracker/data/debug")
_spec = importlib.util.spec_from_file_location("ocr_spike", Path(__file__).parent / "ocr_spike.py")
spike = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spike)


def main() -> None:
    engine = RapidOcrEngine()
    gate = engine._ocr.text_rec
    picture_check = ocr.has_umlaut_dots
    samples = sorted(p for day in ("2026-10-01", "2026-10-02")
                     for p in DEBUG.glob(f"{day}/*-chat/*.png"))[:80]  # fmt: skip
    for label, check in (("before", lambda crop: False), ("now", picture_check)):
        ocr.has_umlaut_dots = check
        for name in ("ocr-spike", "ocr-german"):
            truth = json.loads((PRIVATE / name / "truth.json").read_text(encoding="utf-8"))
            gate.latin_reads, got = 0, {}
            for crop in truth:
                image = cv2.imread(str(PRIVATE / name / "crops" / crop))
                got[crop] = ([line.text for line in engine.read(image)], 0.0)
            s = spike.score(truth, got)
            print(f"{label:6} {name:10} chars {s['char']:.3f}  exact {s['exact_lines']:.2f}  "
                  f"Latin reads {gate.latin_reads}/{len(truth)}", flush=True)  # fmt: skip
        gate.latin_reads = 0
        for path in samples:
            engine.read(cv2.imread(str(path)), scale=4 / 3)
        print(f"{label:6} 4K samples: Latin reads {gate.latin_reads}/{len(samples)}", flush=True)
    ocr.has_umlaut_dots = picture_check


if __name__ == "__main__":
    main()

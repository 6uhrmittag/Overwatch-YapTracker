"""Phase 3 of the OCR POC (#608): the #118 sets, whole engine, with another recognizer swapped in.

    python tools/ocr_train/bench118.py ours=train/crnn1

fixtures/private/ocr-spike (English, 1440p) and ocr-german (German) are chat-box crops with a
hand-made truth, older than and apart from everything the POC trained on, and the only 1440p
data here. Each is read by the app's engine (detection, 2x scale) once as shipped and once per
given model in place of both recognizers, and scored with tools/ocr_spike.py like #118 was:
so these numbers sit on the #118 scale (bar: 99.8 % EN chars, 97.9 % DE).
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent))
import bench  # noqa: E402
import common  # noqa: E402

from yaptracker.ocr.engine import RapidOcrEngine  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "ocr_spike", Path(__file__).parents[1] / "ocr_spike.py"
)
spike = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spike)


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args.add_argument("models", nargs="*", help="name=folder with rec.onnx and dict.txt")
    opts = args.parse_args()
    private = common.private()
    engines = {"app, as shipped": RapidOcrEngine()}
    for item in opts.models:
        name, folder = item.split("=", 1)
        engine = RapidOcrEngine()
        engine._ocr.text_rec = bench.recognizer(private / folder / "rec.onnx",
                                                private / folder / "dict.txt")  # fmt: skip
        engines[name] = engine
    for folder in ("ocr-spike", "ocr-german"):
        root = private.parent / folder
        truth = json.loads((root / "truth.json").read_text(encoding="utf-8"))
        print(f"\n{folder}: {len(truth)} pictures, {sum(len(v) for v in truth.values())} lines")
        for name, engine in engines.items():
            got = {}
            for crop in truth:
                image = cv2.imread(str(root / "crops" / crop))
                if hasattr(engine._ocr.text_rec, "always"):
                    lines = engine.read(image)
                else:  # a swapped-in recognizer has no Latin switch to flip
                    big = cv2.resize(image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                    result, _ = engine._ocr(big)
                    lines = [type("L", (), {"text": t}) for _box, t, _s in result or []]
                got[crop] = ([line.text for line in lines], 0.0)
            s = spike.score(truth, got)
            print(f"  {name:22} chars {s['char']:.3f}  (no spaces {s['char_nospace']:.3f})  "
                  f"exact lines {s['exact_lines']:.2f}  names {s['names']:.2f}")  # fmt: skip


if __name__ == "__main__":
    main()

"""Phase 3 of the OCR POC (#608): the #118 sets, whole engine, with another recognizer swapped in.

    python tools/ocr_train/bench118.py ours=train/crnn1

fixtures/private/ocr-spike (English, 1440p) and ocr-german (German) are chat-box crops with a
hand-made truth, older than the POC's training data and the only 1440p data here. Not fully
apart from it: no picture, name or phrase of theirs is trained on, but everyday words ("ich",
"danke", "gg") are also in synth.py's word lists. Each set is read by the app's engine
(detection, 2x scale) once as shipped and, per given model, with it alone and with it as the
main reader before the app's Latin second read; scored with tools/ocr_spike.py like #118 was,
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
    common.no_game()
    cv2.setNumThreads(1)
    engines = bench.engines(private, opts.models)
    for folder in ("ocr-spike", "ocr-german"):
        root = private.parent / folder
        truth = json.loads((root / "truth.json").read_text(encoding="utf-8"))
        print(f"\n{folder}: {len(truth)} pictures, {sum(len(v) for v in truth.values())} lines")
        for name, engine in engines.items():
            got = {}
            for crop in truth:
                image = cv2.imread(str(root / "crops" / crop))
                lines = engine.read(image)
                got[crop] = ([line.text for line in lines], 0.0)
            s = spike.score(truth, got)
            print(f"  {name:22} chars {s['char']:.3f}  (no spaces {s['char_nospace']:.3f})  "
                  f"exact lines {s['exact_lines']:.2f}  names {s['names']:.2f}")  # fmt: skip


if __name__ == "__main__":
    main()

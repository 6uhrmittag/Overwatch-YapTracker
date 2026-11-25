"""Phase 3 of the OCR POC (#608): recognizers side by side on the very same line crops.

    python tools/ocr_train/bench.py                      # the app's recognizers
    python tools/ocr_train/bench.py ours=train/run1      # plus train/run1/rec.onnx + dict.txt

Detection is the same for all: the crops cut once by crops.py. Each recognizer reads every
crop of the gold rows on one thread; the crops of a row are joined and scored like any reading
(score.py: speaker and text apart, through the app's parser). So the numbers compare
recognizers only, and the baseline is one fresh read, not the stored best-of-several text.
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
import score  # noqa: E402

from yaptracker.ocr.engine import LATIN_KEYS, LATIN_REC, RapidOcrEngine  # noqa: E402

ONE_THREAD = {"intra_op_num_threads": 1, "inter_op_num_threads": 1}


def recognizer(model: Path, keys: Path):
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR(rec_model_path=str(model), rec_keys_path=str(keys), **ONE_THREAD).text_rec


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args.add_argument("models", nargs="*", help="name=folder with rec.onnx and dict.txt")
    opts = args.parse_args()
    private = common.private()
    if common.game_running():
        sys.exit("Overwatch is running: no timed pass now")
    cv2.setNumThreads(1)
    gold = score.load(private)
    with (private / "crops.jsonl").open(encoding="utf-8") as f:
        parts = {r["id"]: r["crops"] for r in map(json.loads, f)}
    crops = {g["id"]: [cv2.imread(str(private / "crops" / f"{g['id']}_{p['k']}.png"))
                       for p in parts[g["id"]]] for g in gold}  # fmt: skip
    app = RapidOcrEngine()._ocr.text_rec  # the app's pair: default model, Latin when German
    engines = {
        "app: default (PP-OCRv4)": app.default,
        "app: Latin (PP-OCRv5 mobile)": recognizer(LATIN_REC, LATIN_KEYS),
        "app: both, as shipped": app,
    }
    for item in opts.models:
        name, folder = item.split("=", 1)
        engines[name] = recognizer(private / folder / "rec.onnx", private / folder / "dict.txt")
    n_crops = sum(len(c) for c in crops.values())
    print(f"{len(gold)} gold rows, {n_crops} crops")
    for name, read in engines.items():
        got, times = {}, []
        for g in gold:
            start = time.perf_counter()
            result = read(crops[g["id"]])[0] if crops[g["id"]] else []
            times.append((time.perf_counter() - start) * 1000)
            got[g["id"]] = score.fields(" ".join(text for text, *_ in result))
        print(f"\n{name}: {sum(times) / n_crops:.1f} ms per crop, "
              f"{statistics.median(times):.0f} ms per row (median)")  # fmt: skip
        for bucket, part in score.buckets(gold).items():
            if part:
                s = score.score(part, got)
                print(f"  {bucket:18} n={s['lines']:3}  chars {s['chars']:.2%}  "
                      f"lines {s['exact']:.1%}  names {s['names']:.1%}")  # fmt: skip


if __name__ == "__main__":
    main()

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
import re
import sqlite3
import statistics
import sys
import threading
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
import score  # noqa: E402

from yaptracker.ocr.engine import LATIN_KEYS, LATIN_REC, RapidOcrEngine  # noqa: E402

_TO = re.compile(r" to (\S+) \(")  # "... to Name (Hero): Hello!"
ONE_THREAD = {"intra_op_num_threads": 1, "inter_op_num_threads": 1}


def recognizer(model: Path, keys: Path):
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR(rec_model_path=str(model), rec_keys_path=str(keys), **ONE_THREAD).text_rec


class Alone:
    """A recognizer in the engine's slot without the app's second read: `always` is the switch
    engine.read() flips for it, here without effect."""

    def __init__(self, read) -> None:
        self.read, self.always, self.latin_reads = read, threading.local(), 0

    def __call__(self, crops, return_word_box: bool = False):
        return self.read(crops, return_word_box)


def engines(private: Path, models: list[str]) -> dict[str, RapidOcrEngine]:
    """The app's engine as shipped, and per `name=folder` two more: that recognizer alone, and
    as the main reader with the app's Latin model still reading German-looking lines again."""
    out = {"app, as shipped": RapidOcrEngine()}
    for item in models:
        name, folder = item.split("=", 1)
        ours = recognizer(private / folder / "rec.onnx", private / folder / "dict.txt")
        alone, both = RapidOcrEngine(), RapidOcrEngine()
        alone._ocr.text_rec = Alone(ours)
        both._ocr.text_rec.default = ours
        out[name] = alone
        out[f"{name} + Latin second read"] = both
    return out


def name_buckets(private: Path, gold: list[dict]) -> dict[str, list[dict]]:
    """Whose name is on the row (#624): a reader may know frequent names by heart, so names it
    never saw in training count apart from the user's own and the crew's (most of the rows)."""
    with (private / "labels.jsonl").open(encoding="utf-8") as f:
        texts = [r["text"] for r in map(json.loads, f) if r["split"] != "test"]
    # a name counts as seen as the speaker of a line or as the one a comms line goes to
    seen = {score.fields(text)[0] for text in texts} | {
        name for text in texts for name in _TO.findall(text)
    }
    db = sqlite3.connect(private / "dbcopy" / "yaptracker.db")
    own = {i for (i,) in db.execute("SELECT id FROM chat_messages WHERE role IS NOT NULL")}
    named = [g for g in gold if g["gold"][0]]
    return {
        "names: never in training": [g for g in named if g["gold"][0] not in seen],
        "names: own and crew": [g for g in named if g["id"] in own],
        "names: others, in training": [
            g for g in named if g["id"] not in own and g["gold"][0] in seen
        ],
    }


def confidence(gold: list[dict], got: dict, lowest: dict) -> str:
    """Does the score still tell a right read from a wrong one? Keep-best relies on it."""
    right = [lowest[g["id"]] for g in gold if got[g["id"]] == g["gold"]]
    wrong = [lowest[g["id"]] for g in gold if got[g["id"]] != g["gold"]]
    if not right or not wrong:
        return ""
    return (f"  confidence: right {statistics.median(right):.3f} (median, n={len(right)}), "
            f"wrong {statistics.median(wrong):.3f} (n={len(wrong)}); "
            f"wrong at 0.95 or more: {sum(c >= 0.95 for c in wrong)}, "
            f"right under 0.90: {sum(c < 0.9 for c in right)}")  # fmt: skip


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args.add_argument("models", nargs="*", help="name=folder with rec.onnx and dict.txt")
    opts = args.parse_args()
    private = common.private()
    common.no_game()
    cv2.setNumThreads(1)
    gold = score.load(private)
    with (private / "crops.jsonl").open(encoding="utf-8") as f:
        parts = {r["id"]: r["crops"] for r in map(json.loads, f)}
    crops = {g["id"]: [cv2.imread(str(private / "crops" / f"{g['id']}_{p['k']}.png"))
                       for p in parts[g["id"]]] for g in gold}  # fmt: skip
    app = RapidOcrEngine()._ocr.text_rec  # the app's pair: default model, Latin when German
    readers = {
        "app: default (PP-OCRv4)": app.default,
        "app: Latin (PP-OCRv5 mobile)": recognizer(LATIN_REC, LATIN_KEYS),
    }
    readers |= {name: e._ocr.text_rec for name, e in engines(private, opts.models).items()}
    n_crops = sum(len(c) for c in crops.values())
    print(f"{len(gold)} gold rows, {n_crops} crops")
    for name, read in readers.items():
        got, times, lowest = {}, [], {}
        for g in gold:
            start = time.perf_counter()
            result = read(crops[g["id"]])[0] if crops[g["id"]] else []
            times.append((time.perf_counter() - start) * 1000)
            got[g["id"]] = score.fields(" ".join(text for text, *_ in result))
            lowest[g["id"]] = min((float(s) for _text, s, *_ in result), default=0.0)
        print(f"\n{name}: {sum(times) / n_crops:.1f} ms per crop, "
              f"{statistics.median(times):.0f} ms per row (median)")  # fmt: skip
        for bucket, part in (score.buckets(gold) | name_buckets(private, gold)).items():
            if part:
                s = score.score(part, got)
                people = len({g["gold"][0] for g in part}) if bucket.startswith("names") else 0
                print(f"  {bucket:26} n={s['lines']:3}  chars {s['chars']:.2%}  "
                      f"lines {s['exact']:.1%}  names {s['names']:.1%}"
                      + (f"  ({people} different names)" if people else ""))  # fmt: skip
        print(confidence(gold, got, lowest))


if __name__ == "__main__":
    main()

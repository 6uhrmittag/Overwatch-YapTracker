"""Phase 2 of the OCR POC (#608): the line crops a recognizer really sees, cut from every row.

    python tools/ocr_train/crops.py

A recognizer never gets a whole row: RapidOCR's detection finds the text boxes and hands each
one over as a crop. So the training pictures are cut the same way: the app's own engine reads
every whole-row picture at the 4K scale, and what its recognizer was handed is saved as
crops/<id>_<k>.png with what it read (crops.jsonl). Resumable; private, like everything here.
"""

import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
from inventory import ROW_MIN_WIDTH  # noqa: E402
from reread_rapid import SCALE_4K  # noqa: E402

from yaptracker.ocr.engine import RapidOcrEngine  # noqa: E402

CHECK_EVERY = 200  # rows between two looks for Overwatch.exe


class Recorder:
    """Stands where the recognizer stands and keeps what it was given and what it read."""

    def __init__(self, inner) -> None:
        self.inner, self.seen = inner, []
        self.always = inner.always  # the engine switches the Latin read through it

    def __call__(self, crops, return_word_box: bool = False):
        result = self.inner(crops, return_word_box)
        self.seen = [(crop, text, float(score)) for crop, (text, score, *_) in
                     zip(crops, result[0], strict=True)]  # fmt: skip
        return result


def main() -> None:
    private = common.private()
    if common.game_running():
        sys.exit("Overwatch is running: not now")
    with (private / "dataset.jsonl").open(encoding="utf-8") as f:
        data = [r for r in map(json.loads, f) if r["width"] >= ROW_MIN_WIDTH]
    folder, index = private / "crops", private / "crops.jsonl"
    folder.mkdir(exist_ok=True)
    done = set()
    if index.exists():
        with index.open(encoding="utf-8") as f:
            done = {json.loads(line)["id"] for line in f if line.strip().endswith("}")}
    cv2.setNumThreads(1)
    engine = RapidOcrEngine()
    recorder = engine._ocr.text_rec = Recorder(engine._ocr.text_rec)
    todo = [r for r in data if r["id"] not in done]
    with index.open("a", encoding="utf-8") as out:
        for n, r in enumerate(todo):
            if n % CHECK_EVERY == 0 and n and common.game_running():
                sys.exit(f"Overwatch is running: stopped after {n} of {len(todo)} rows")
            recorder.seen = []
            engine.read(cv2.imread(str(private / r["picture"])), scale=SCALE_4K)
            parts = []
            for k, (crop, text, score) in enumerate(recorder.seen):
                cv2.imwrite(str(folder / f"{r['id']}_{k}.png"), crop)
                parts.append({"k": k, "read": text, "confidence": round(score, 3),
                              "width": crop.shape[1], "height": crop.shape[0]})  # fmt: skip
            out.write(json.dumps({"id": r["id"], "crops": parts}, ensure_ascii=False) + "\n")
    print(f"{len(todo)} rows cut, {len(done)} were there")


if __name__ == "__main__":
    main()

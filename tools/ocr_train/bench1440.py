"""#624: the gold rows as a 1440p screen shows them, whole engine, per recognizer.

    python tools/ocr_train/bench1440.py paddle=train/paddle2

All real data is 4K (Marv's PC); Void plays at 1440p. So every gold row picture is shrunk to
2/3 (what 1440p shows) and read as the app reads a 1440p window (2x scale, detection and all),
and next to it at its own 4K size (4/3 scale), so the loss from the resolution alone shows.
Scored like any reading (score.py). An imitation: real 1440p rendering isn't a shrunk 4K
picture; the #118 sets (bench118.py) are the real 1440p data, but few.
"""

import argparse
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent))
import bench  # noqa: E402
import common  # noqa: E402
import score  # noqa: E402
from reread_rapid import SCALE_4K  # noqa: E402

SCALE_1440 = 2.0  # the app's scale for a 1440-high window


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args.add_argument("models", nargs="*", help="name=folder with rec.onnx and dict.txt")
    opts = args.parse_args()
    private = common.private()
    common.no_game()
    cv2.setNumThreads(1)
    gold = score.load(private)
    pictures = {g["id"]: cv2.imread(str(private / g["picture"])) for g in gold}
    for name, engine in bench.engines(private, opts.models).items():
        print(f"\n{name}")
        for label, shrink, scale in (("4K", 1.0, SCALE_4K), ("as 1440p", 2 / 3, SCALE_1440)):
            got = {}
            for g in gold:
                image = pictures[g["id"]]
                if shrink != 1.0:
                    image = cv2.resize(image, None, fx=shrink, fy=shrink,
                                       interpolation=cv2.INTER_AREA)  # fmt: skip
                lines = engine.read(image, scale=scale)
                got[g["id"]] = score.fields(" ".join(line.text for line in lines))
            for bucket, part in score.buckets(gold).items():
                if part and bucket in ("all", "EN", "DE (umlauts/ß)"):
                    s = score.score(part, got)
                    print(f"  {label:9} {bucket:15} n={s['lines']:3}  chars {s['chars']:.2%}  "
                          f"lines {s['exact']:.1%}  names {s['names']:.1%}")  # fmt: skip


if __name__ == "__main__":
    main()

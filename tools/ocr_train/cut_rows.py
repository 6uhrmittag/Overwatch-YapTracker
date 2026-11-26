"""Half-cut rows for training, labelled as nothing (#632).

    python tools/ocr_train/cut_rows.py

The opened chat's edge cuts its top row in half, and detection hands the recognizer the lower
half of the letters. A recognizer trained only on whole rows reads something line-shaped into
it ("[Plckte]: Heyyy"), and the app then can't tell it from a weak reading of a real
line. So it learns that half a row says nothing: every SHARE-th real train and dev crop loses
its upper 35-55 % and gets the empty label (cutrows.jsonl, pictures in cutrows/). With an
empty reading RapidOCR drops the box, as it does for any box nothing is read in.
"""

import json
import random
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402

CUT = (0.35, 0.55)  # of the crop's height, from the top: what the box's edge takes
USUAL = 0.85  # cut rows no wider for their height than this share of the real crops
SHARE = 3  # (fewer qualify now: every third crop is tried)


def main() -> None:
    private, rng = common.private(), random.Random(632)
    with (private / "labels.jsonl").open(encoding="utf-8") as f:
        rows = [r for r in map(json.loads, f) if r["split"] in ("train", "dev")]
    if not rows:
        sys.exit("no train or dev crops in labels.jsonl yet: run labels.py first")
    folder = private / "cutrows"
    folder.mkdir(exist_ok=True)
    out = []
    # The trainer batches crops of a similar width-to-height ratio. Half a row is twice as wide
    # for its height, so cut rows of long lines would fill the widest batches alone: nothing
    # but empty labels, which teaches nothing (and crashed warpctc). Only cut rows that stay
    # among the usual ratios, so they always share a batch with real rows.
    sizes = [Image.open(private / r["crop"]).size for r in rows[::25]]
    ratios = sorted(width / height for width, height in sizes)
    widest = ratios[int(len(ratios) * USUAL)]
    for r in rows[::SHARE]:
        image = Image.open(private / r["crop"]).convert("RGB")
        top = round(image.height * rng.uniform(*CUT))
        if image.height - top < 8 or image.width / (image.height - top) > widest:
            continue
        name = f"cutrows/{Path(r['crop']).stem}.png"
        image.crop((0, top, image.width, image.height)).save(private / name)
        out.append({"crop": name, "text": "", "split": r["split"], "id": r["id"],
                    "source": "cut row"})  # fmt: skip
    with (private / "cutrows.jsonl").open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in out)
    print(f"{len(out)} half-cut rows ({sum(r['split'] == 'dev' for r in out)} of them dev)")


if __name__ == "__main__":
    main()

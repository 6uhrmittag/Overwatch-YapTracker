"""Phase 1 of the OCR POC (#608): pick the gold lines and draw numbered sheets to label from.

    python tools/ocr_train/gold_sheets.py

Picks ~300 lines (every hand-corrected and every umlaut line, then the newest evenings spread
over channels, wraps and glyph lines) and writes fixtures/private/ocr/gold/sample.json plus
sheets/NN.png: the pictures only, numbered, no stored text, so the labels are made blind.
The labels go into gold/labels.json as {"<message id>": "<the row as it reads>"} (private);
sample.json maps a sheet number to its message id. With labels there, a new pick is refused.

"Every umlaut line" means every line RapidOCR stored with an umlaut: lines whose umlauts it
missed aren't found this way, so the DE bucket flatters the stored text. Say so with the number.
"""

import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
from inventory import ROW_MIN_WIDTH, WRAP_HEIGHT  # noqa: E402

TARGET = 300
PER_SHEET = 12
SAME_LINE_MAX = 2  # "Thanks!" from one player fills evenings: at most twice in the sample
MARGIN = 70  # the number's column


def pick(data: list[dict]) -> list[dict]:
    rng = random.Random(608)
    whole = [r for r in data if r["width"] >= ROW_MIN_WIDTH]
    must = [r for r in whole if r["edited_text"] is not None or r["german"]]
    rest = [r for r in whole if r["split"] == "test" and r not in must]
    rng.shuffle(rest)
    # hard ones first, then the plain rest in its shuffled order
    rest.sort(key=lambda r: not (r["glyphs"] or r["height"] >= WRAP_HEIGHT))
    seen: dict[tuple, int] = {}
    chosen = list(must)
    for r in rest:
        key = (r["speaker"], r["ocr_text"])
        if len(chosen) < TARGET and seen.get(key, 0) < SAME_LINE_MAX:
            seen[key] = seen.get(key, 0) + 1
            chosen.append(r)
    rng.shuffle(chosen)
    return chosen


def sheets(chosen: list[dict], private: Path) -> None:
    folder = private / "gold" / "sheets"
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.png"):
        old.unlink()
    for start in range(0, len(chosen), PER_SHEET):
        part = [Image.open(private / r["picture"]).convert("RGB")
                for r in chosen[start : start + PER_SHEET]]  # fmt: skip
        width = MARGIN + max(p.width for p in part)
        sheet = Image.new("RGB", (width, sum(p.height + 8 for p in part)), (70, 0, 90))
        draw, y = ImageDraw.Draw(sheet), 0
        for i, p in enumerate(part):
            draw.text((6, y + p.height // 2 - 6), str(start + i), fill=(255, 255, 255))
            sheet.paste(p, (MARGIN, y))
            y += p.height + 8
        sheet.save(folder / f"{start // PER_SHEET:02}.png")


def main() -> None:
    private = common.private()
    with (private / "dataset.jsonl").open(encoding="utf-8") as f:
        data = [json.loads(line) for line in f]
    if (private / "gold" / "labels.json").exists():
        sys.exit("gold/labels.json exists: a new pick would orphan the labels (move it away first)")
    chosen = pick(data)
    (private / "gold").mkdir(exist_ok=True)
    (private / "gold" / "sample.json").write_text(json.dumps([r["id"] for r in chosen]))
    sheets(chosen, private)
    print(f"{len(chosen)} lines on {-(-len(chosen) // PER_SHEET)} sheets:",
          f"{sum(r['german'] for r in chosen)} umlaut,",
          f"{sum(r['edited_text'] is not None for r in chosen)} hand-corrected,",
          f"{sum(r['glyphs'] for r in chosen)} glyph,",
          f"{sum(r['height'] >= WRAP_HEIGHT for r in chosen)} wrapped")  # fmt: skip


if __name__ == "__main__":
    main()

"""Phase 0 of the OCR POC (#608): copy the data, join pictures to their text, split by evening.

    python tools/ocr_train/inventory.py            # copy from the app's data folder, then count
    python tools/ocr_train/inventory.py --no-copy  # count the copy that is already there

Writes fixtures/private/ocr/dataset.jsonl (one stored line per row, private) and prints
aggregates only. The app's live DB is never opened: its files are copied first.

Made for 4K evenings (all there are on Marv's PC): a whole row is ROW_MIN_WIDTH or wider and a
wrap WRAP_HEIGHT or higher. Rows of a 1440p chat box would be counted as "old box crops"; the
report shows the row widths, so that can't go unseen. Once gold lines exist, the test evenings
are frozen (gold/split.json) and every gold line is test, whatever its evening.
"""

import argparse
import json
import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402

from yaptracker.days import day_of  # noqa: E402

TEST_EVENINGS = 2  # the newest evenings are the test set, with every hand-corrected line
ROW_MIN_WIDTH = 900  # narrower: a picture from before whole rows were kept (one OCR box)
WRAP_HEIGHT = 62  # a 4K row is 34-56 px high; from here on it is a wrapped (two-row) line
_GERMAN = set("äöüßÄÖÜ")


def copy(private: Path) -> None:
    """The DB files and the pictures. SQLite's backup can't open the live DB over /mnt/c (disk
    I/O error), so the files are copied and the copy is checked; a torn copy fails loudly."""
    if common.game_running():
        sys.exit("Overwatch is running: the copy waits (or use --no-copy)")
    (private / "dbcopy").mkdir(parents=True, exist_ok=True)
    for name in ("yaptracker.db", "yaptracker.db-wal", "yaptracker.db-shm"):
        (private / "dbcopy" / name).unlink(missing_ok=True)  # never an old WAL on a new DB
    for name in ("yaptracker.db", "yaptracker.db-wal"):
        if (common.DATA / name).exists():
            shutil.copy2(common.DATA / name, private / "dbcopy" / name)
    check = sqlite3.connect(private / "dbcopy" / "yaptracker.db")
    if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        sys.exit("the DB copy is torn (the app wrote meanwhile): run again")
    check.close()
    shutil.copytree(common.DATA / "lines", private / "lines", dirs_exist_ok=True)


def rows(private: Path) -> list[dict]:
    pictures = {int(p.stem): p for p in (private / "lines").rglob("*.webp") if p.stem.isdigit()}
    db = sqlite3.connect(private / "dbcopy" / "yaptracker.db")
    db.row_factory = sqlite3.Row
    out = []
    for m in db.execute("SELECT * FROM chat_messages WHERE deleted_at IS NULL ORDER BY id"):
        path = pictures.get(m["id"])
        if path is None:
            continue
        width, height = Image.open(path).size
        edited = m["edited_at"] is not None
        out.append({
            "id": m["id"], "picture": str(path.relative_to(private)), "evening": day_of(m["ts"]),
            "channel": m["channel"], "speaker": m["speaker_raw"], "hero": m["hero"],
            # what RapidOCR read: a hand-corrected line keeps it in original_text
            "ocr_text": m["original_text"] if edited else m["text"],
            "edited_text": m["text"] if edited else None,
            "confidence": m["ocr_confidence"], "glyphs": bool(m["has_glyphs"]),
            "german": bool(_GERMAN & set(m["text"])),
            "width": width, "height": height,
        })  # fmt: skip
    evenings = sorted({r["evening"] for r in out})
    split, sample = private / "gold" / "split.json", private / "gold" / "sample.json"
    gold = set(json.loads(sample.read_text())) if sample.exists() else set()
    if split.exists():  # frozen with the gold lines: a new evening must not move them to train
        first_test = json.loads(split.read_text())["test_from"]
    else:
        first_test = evenings[-TEST_EVENINGS:][0] if evenings else ""
        if gold:
            split.write_text(json.dumps({"test_from": first_test}))
    for r in out:
        test = r["evening"] >= first_test or r["edited_text"] is not None or r["id"] in gold
        r["split"] = "test" if test else "train"
    return out


def report(data: list[dict], private: Path) -> None:
    db = sqlite3.connect(private / "dbcopy" / "yaptracker.db")
    messages, deleted = db.execute(
        "SELECT count(*), count(deleted_at) FROM chat_messages"
    ).fetchone()
    files = sum(1 for _ in (private / "lines").rglob("*.webp"))
    print(f"messages {messages} (deleted {deleted}), picture files {files}, joined {len(data)}")
    evenings = sorted({r["evening"] for r in data})
    print(f"evenings {len(evenings)}: {evenings[0]} .. {evenings[-1]}")
    for split in ("train", "test"):
        part = [r for r in data if r["split"] == split]
        if not part:
            print(f"\n{split}: no lines")
            continue
        days = sorted({r["evening"] for r in part})
        print(f"\n{split}: {len(part)} lines, {len(days)} evenings ({days[0]} .. {days[-1]})")
        print("  channel   ", dict(Counter(r["channel"] for r in part).most_common()))
        print("  whole rows", sum(r["width"] >= ROW_MIN_WIDTH for r in part),
              "| old box crops", sum(r["width"] < ROW_MIN_WIDTH for r in part))  # fmt: skip
        print("  row width ", dict(Counter(
            r["width"] for r in part if r["width"] >= ROW_MIN_WIDTH).most_common()))  # fmt: skip
        print("  wrapped   ", sum(r["height"] >= WRAP_HEIGHT for r in part))
        print("  glyphs    ", sum(r["glyphs"] for r in part),
              "| umlauts/ß", sum(r["german"] for r in part),
              "| hand-corrected", sum(r["edited_text"] is not None for r in part))  # fmt: skip
        low = sum((r["confidence"] or 0) < 0.9 for r in part)
        print("  confidence < 0.9:", low)


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args.add_argument("--no-copy", action="store_true", help="use the copy that is already there")
    opts = args.parse_args()
    private = common.private()
    if not opts.no_copy:
        copy(private)
    data = rows(private)
    with (private / "dataset.jsonl").open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in data)
    report(data, private)


if __name__ == "__main__":
    main()

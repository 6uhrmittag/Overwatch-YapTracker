"""Phase 2 of the OCR POC (#608): a label for every line crop, without anyone typing them.

    python tools/ocr_train/labels.py

Silver label of a row = the local model's reading (readings/glm.jsonl), taken only where
 - it says the same as the text the app stored (speaker and text), or
 - a second model (readings/qwen.jsonl, if there) says the same where the stored text differs:
   these are the lines RapidOCR got wrong, the ones worth learning from.
Gold rows keep their hand label and are test only. The row's label is then cut at the same
places detection cut the picture (crops.jsonl), by lining it up with what RapidOCR read in each
crop; a row that doesn't line up is left out and counted. Writes labels.jsonl:
{"crop", "text", "split": train | dev | test, "id", "source"}. Dev = the newest DEV_EVENINGS
train evenings: checkpoints are chosen there, never on gold.
"""

import json
import sys
from collections import Counter
from pathlib import Path

from rapidfuzz.distance import Levenshtein

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
import score  # noqa: E402

DEV_EVENINGS = 3
LINES_UP = 0.6  # a crop's label must be this similar to what RapidOCR read in it


def readings(path: Path) -> dict[int, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return {r["id"]: r["row"] for r in map(json.loads, f)}


def cut(row: str, reads: list[str]) -> list[str] | None:
    """The row's label in as many pieces as there are crops, or None when it doesn't line up."""
    if len(reads) == 1:
        return [row] if Levenshtein.normalized_similarity(row, reads[0]) >= LINES_UP else None
    joined, ends, at = " ".join(reads), [], 0
    for read in reads[:-1]:
        at += len(read)
        ends.append(at)  # the joining space after this crop's text
        at += 1
    where = {}  # place in `joined` -> place in `row`
    for tag, a0, a1, b0, _b1 in Levenshtein.opcodes(joined, row):
        for i in range(a0, a1 + 1):
            where.setdefault(i, b0 + (i - a0 if tag in ("equal", "replace") else 0))
    cuts = [0] + [where.get(e, len(row)) for e in ends] + [len(row)]
    pieces = [row[a:b].strip() for a, b in zip(cuts, cuts[1:], strict=False)]
    for piece, read in zip(pieces, reads, strict=True):
        if piece and Levenshtein.normalized_similarity(piece, read) < LINES_UP:
            return None
    return pieces


def main() -> None:
    private = common.private()
    with (private / "dataset.jsonl").open(encoding="utf-8") as f:
        data = {r["id"]: r for r in map(json.loads, f)}
    with (private / "crops.jsonl").open(encoding="utf-8") as f:
        crops = {r["id"]: r["crops"] for r in map(json.loads, f)}
    gold_ids = json.loads((private / "gold" / "sample.json").read_text())
    gold = json.loads((private / "gold" / "labels.json").read_text(encoding="utf-8"))
    first, second = (
        readings(private / "readings" / "glm.jsonl"),
        readings(private / "readings" / "qwen.jsonl"),
    )
    train_days = sorted({r["evening"] for r in data.values() if r["split"] == "train"})
    dev_days = set(train_days[-DEV_EVENINGS:])
    counts, out = Counter(), []
    for message_id, parts in crops.items():
        r = data[message_id]
        if message_id in gold_ids:
            row, source, split = gold[str(message_id)], "gold", "test"
        elif r["split"] == "test":
            counts["test evening without a gold label: left out"] += 1
            continue
        else:
            split = "dev" if r["evening"] in dev_days else "train"
            row = first.get(message_id)
            if row is None:
                counts["not re-read yet"] += 1
                continue
            stored = (r["speaker"] or "", common.plain(r["ocr_text"]))
            if score.fields(row) == stored:
                source = "model = stored"
            elif message_id in second and score.fields(second[message_id]) == score.fields(row):
                source = "two models against stored"
            else:
                counts["no agreement: left out"] += 1
                continue
        # the models write a system line's yellow dot as "- " or "• ": not text
        row = " ".join(common.plain(row).split()).lstrip("-•·* ")
        pieces = cut(row, [p["read"] for p in parts]) if parts else None
        if pieces is None:
            counts["doesn't line up with the crops: left out"] += 1
            continue
        counts[f"rows, {source}"] += 1
        for part, piece in zip(parts, pieces, strict=True):
            if not piece:  # detection boxed an icon: nothing to read there
                counts["crops without text (icons)"] += 1
                continue
            out.append({"crop": f"crops/{message_id}_{part['k']}.png", "text": piece,
                        "split": split, "id": message_id, "source": source})  # fmt: skip
    with (private / "labels.jsonl").open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in out)
    for what, n in sorted(counts.items()):
        print(f"{n:6}  {what}")
    reads = {f"crops/{i}_{p['k']}.png": p["read"] for i, parts in crops.items() for p in parts}
    differ = sum(r["text"] != reads[r["crop"]] for r in out)
    print(dict(Counter(r["split"] for r in out)), f"crops; {differ} differ from RapidOCR's read")


if __name__ == "__main__":
    main()

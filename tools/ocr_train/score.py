"""Scores readings against the gold lines (#608): RapidOCR's stored text, and any re-read.

    python tools/ocr_train/score.py                       # the stored text only
    python tools/ocr_train/score.py vlm=readings/vlm.jsonl  # plus a re-read ({"id":, "row":})

Gold (gold/labels.json) and a re-read are whole rows as they read on the picture; both go
through the app's own parser, so every engine is compared as the app would store it: speaker
and text apart, icon marks removed, spaces collapsed. Paths are relative to
fixtures/private/ocr. Prints aggregates; --misses lists the lines (private, never post all).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
from inventory import WRAP_HEIGHT  # noqa: E402

from yaptracker.capture.source import Region  # noqa: E402
from yaptracker.ocr.engine import OcrLine  # noqa: E402
from yaptracker.parser import parse  # noqa: E402

_GERMAN = set("äöüßÄÖÜ")
_FOLD = str.maketrans({"I": "l", "|": "l", "0": "O", "o": "O"})  # same shapes in the chat font


def fields(row: str) -> tuple[str, str]:
    """(speaker, text) of a row, as the app's parser splits it."""
    row = " ".join(row.split())
    if not row:
        return "", ""
    lines = parse([OcrLine(text=row, confidence=1.0, box=Region(0, 0, 900, 40))])
    return lines[0].speaker or "", common.plain(lines[0].text)


def load(private: Path) -> list[dict]:
    """The gold lines: dataset row + gold speaker/text."""
    with (private / "dataset.jsonl").open(encoding="utf-8") as f:
        data = {r["id"]: r for r in map(json.loads, f)}
    ids = json.loads((private / "gold" / "sample.json").read_text())
    labels = json.loads((private / "gold" / "labels.json").read_text(encoding="utf-8"))
    out = []
    for n, message_id in enumerate(ids):
        speaker, text = fields(labels[str(n)])
        out.append({**data[message_id], "n": n, "gold": (speaker, text)})
    return out


def stored(gold: list[dict]) -> dict[int, tuple[str, str]]:
    return {g["id"]: (g["speaker"] or "", common.plain(g["ocr_text"])) for g in gold}


def reread(path: Path) -> dict[int, tuple[str, str]]:
    with path.open(encoding="utf-8") as f:
        return {r["id"]: fields(r["row"]) for r in map(json.loads, f)}


def score(gold: list[dict], got: dict[int, tuple[str, str]], fold: bool = False) -> dict:
    wrong = chars = exact = names = names_right = 0
    for g in gold:
        truth, read = g["gold"], got.get(g["id"], ("", ""))
        if fold:
            truth = tuple(s.translate(_FOLD) for s in truth)
            read = tuple(s.translate(_FOLD) for s in read)
        for t, r in zip(truth, read, strict=True):
            w, c = common.errors(t, r)
            wrong, chars = wrong + w, chars + c
        exact += truth == read
        if truth[0]:
            names += 1
            names_right += truth[0] == read[0]
    return {"lines": len(gold), "chars": 1 - wrong / max(chars, 1), "exact": exact / len(gold),
            "names": names_right / max(names, 1), "names_n": names}  # fmt: skip


def buckets(gold: list[dict]) -> dict[str, list[dict]]:
    german = [g for g in gold if _GERMAN & set("".join(g["gold"]))]
    return {
        "all": gold,
        "EN": [g for g in gold if g not in german],
        "DE (umlauts/ß)": german,
        "with icons": [g for g in gold if g["glyphs"]],
        "wrapped": [g for g in gold if g["height"] >= WRAP_HEIGHT],
        "match chat": [g for g in gold if g["channel"] == "match"],
        "team (chat+comms)": [g for g in gold if g["channel"] == "team"],
        "system": [g for g in gold if g["channel"] == "system"],
    }


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args.add_argument("readings", nargs="*", help="name=path.jsonl of a re-read")
    args.add_argument("--misses", action="store_true", help="list every line read wrong")
    opts = args.parse_args()
    private = common.private()
    gold = load(private)
    engines = {"RapidOCR (stored)": stored(gold)}
    for item in opts.readings:
        name, path = item.split("=", 1)
        engines[name] = reread(private / path)
    for name, got in engines.items():
        print(f"\n{name}")
        for bucket, part in buckets(gold).items():
            s, f = score(part, got), score(part, got, fold=True)
            print(
                f"  {bucket:18} n={s['lines']:3}  chars {s['chars']:.2%}  lines {s['exact']:.1%}"
                f"  names {s['names']:.1%} (n={s['names_n']})"
                f"  | I/l, 0/O as one: chars {f['chars']:.2%}  lines {f['exact']:.1%}"
            )
        if opts.misses:
            for g in gold:
                if got.get(g["id"], ("", "")) != g["gold"]:
                    print(f"    {g['n']:3} gold {g['gold']!r}\n        read {got.get(g['id'])!r}")


if __name__ == "__main__":
    main()

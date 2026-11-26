"""#628: what the whole pipeline stores with one reading engine and with another.

    python tools/cpu_replay.py <recording> --engine rapidocr --dump a.txt
    python tools/cpu_replay.py <recording> --engine chat --dump b.txt
    python tools/ocr_train/replay_compare.py a.txt b.txt [--show 30]

The benchmarks read single rows. Here the same recorded match went through detection, parser,
dedup, keep-best and the icon marks, once per engine, and the two stored chat logs are laid
side by side: how many lines, by channel; which lines both have; which are the same line read
differently; which only one side has; repeats; icon marks; and every speaker name with how
often each side stored it. Prints counts; --show lists differing lines (private: a few
snippets may go into an issue, never the list).
"""

import argparse
from collections import Counter
from pathlib import Path

from rapidfuzz import fuzz, process

SAME_LINE = 75  # this similar: one line, read differently


def load(path: Path) -> list[tuple[str, float, str, str]]:
    """(channel, confidence, speaker, text) per stored line, as cpu_replay.py --dump wrote them."""
    rows = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line:
            channel, confidence, speaker, text = line.split("\t", 3)
            rows.append((channel, float(confidence), speaker, text))
    return rows


def shown(row: tuple[str, float, str, str]) -> str:
    return f"{row[2]}: {row[3]}" if row[2] else row[3]


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args.add_argument("a", type=Path)
    args.add_argument("b", type=Path)
    args.add_argument("--show", type=int, default=0, help="list this many differing lines")
    opts = args.parse_args()
    names = [opts.a.stem, opts.b.stem]
    if names[0] == names[1]:  # the same file name in two folders
        names = [str(opts.a), str(opts.b)]
    sides = list(zip(names, (load(opts.a), load(opts.b)), strict=True))
    for name, rows in sides:
        texts = [shown(r) for r in rows]
        repeats = sum(a == b for a, b in zip(texts, texts[1:], strict=False))
        icons = sum("◇" in t or "[icon:" in t for t in texts)
        low = sum(r[1] < 0.9 for r in rows)
        print(
            f"{name}: {len(rows)} lines, {dict(Counter(r[0] for r in rows))}, "
            f"{icons} with an icon mark, {repeats} repeats in a row, {low} below 0.9"
        )
    (name_a, a), (name_b, b) = sides
    lines_a, lines_b = Counter(map(shown, a)), Counter(map(shown, b))
    left, right, same = lines_a - lines_b, lines_b - lines_a, sum((lines_a & lines_b).values())
    pairs, only_a = [], []
    rest = list(right.elements())
    for text in left.elements():
        match = process.extractOne(text, rest, scorer=fuzz.ratio, score_cutoff=SAME_LINE)
        if match:
            pairs.append((text, match[0]))
            rest.remove(match[0])
        else:
            only_a.append(text)
    print(f"\nthe same on both sides: {same}")
    print(f"one line, read differently: {len(pairs)}")
    print(f"only {name_a}: {len(only_a)}   only {name_b}: {len(rest)}")
    names_a = Counter(r[2] for r in a if r[2])
    names_b = Counter(r[2] for r in b if r[2])
    odd = {n for n in names_a | names_b if names_a[n] != names_b[n]}
    print(f"speaker names: {len(names_a)} / {len(names_b)}, "
          f"{len(odd)} stored a different number of times")  # fmt: skip
    if opts.show:
        for n in sorted(odd, key=lambda n: -(names_a[n] + names_b[n]))[: opts.show]:
            print(f"  name {n!r}: {names_a[n]} / {names_b[n]}")
        for x, y in pairs[: opts.show]:
            print(f"  {name_a}: {x}\n  {name_b}: {y}")
        for text in only_a[: opts.show]:
            print(f"  only {name_a}: {text}")
        for text in rest[: opts.show]:
            print(f"  only {name_b}: {text}")


if __name__ == "__main__":
    main()

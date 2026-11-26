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


def load(path: Path) -> list[tuple[str, float, str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        channel, confidence, text = line.split("\t", 2)
        rows.append((channel, float(confidence), text))
    return rows


def speaker(text: str) -> str:
    return text.split(": ", 1)[0] if ": " in text else ""


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args.add_argument("a", type=Path)
    args.add_argument("b", type=Path)
    args.add_argument("--show", type=int, default=0, help="list this many differing lines")
    opts = args.parse_args()
    sides = {opts.a.stem: load(opts.a), opts.b.stem: load(opts.b)}
    for name, rows in sides.items():
        texts = [t for _c, _s, t in rows]
        repeats = sum(a == b for a, b in zip(texts, texts[1:], strict=False))
        icons = sum("◇" in t or "[icon:" in t for t in texts)
        low = sum(s < 0.9 for _c, s, _t in rows)
        print(f"{name}: {len(rows)} lines, {dict(Counter(c for c, _s, _t in rows))}, "
              f"{icons} with an icon mark, {repeats} repeats in a row, {low} under 0.9")  # fmt: skip
    (name_a, a), (name_b, b) = sides.items()
    left = Counter(t for _c, _s, t in a) - Counter(t for _c, _s, t in b)
    right = Counter(t for _c, _s, t in b) - Counter(t for _c, _s, t in a)
    same = sum((Counter(t for _c, _s, t in a) & Counter(t for _c, _s, t in b)).values())
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
    names_a = Counter(speaker(t) for _c, _s, t in a)
    names_b = Counter(speaker(t) for _c, _s, t in b)
    odd = {n for n in names_a | names_b if n and names_a[n] != names_b[n]}
    print(f"speaker names: {len(set(names_a) - {''})} / {len(set(names_b) - {''})}, "
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

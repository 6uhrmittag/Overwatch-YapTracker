"""OCR engine spike (#11, #118): score engines on chat crops against a hand-made ground truth.

    python tools/ocr_spike.py CROPS_DIR TRUTH.json [--winocr NAME=FILE ...]
                              [--rec NAME=MODEL.onnx:DICT.txt ...] [--scales 2]

--rec swaps only the recognition model (same detection), e.g. a Latin one for umlauts (#118).

TRUTH.json maps crop file names to the visual lines they show (wrapped lines separately, half-cut
top line and the open chat's input line left out). Windows OCR runs on Windows only, so its output
comes from tools/ocr_spike_winocr.ps1. Real crops and truth live in fixtures/private/ - print only
aggregate numbers, never lines.
"""

import argparse
import json
import re
import statistics
import time
from pathlib import Path

import cv2
from rapidfuzz.distance import Levenshtein

_NAME = re.compile(r"^\[([^\]]+)\]|^(\S+) \(|to (\S+) \(")


def rapid_lines(engine, image, scale: float) -> tuple[list[str], float]:
    if scale != 1:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    start = time.perf_counter()
    result, _ = engine(image)
    ms = (time.perf_counter() - start) * 1000
    boxes = sorted(((b[0][1] / scale, b[0][0], text) for b, text, _ in result or []))
    lines: list[list[tuple[float, float, str]]] = []
    for box in boxes:  # boxes on (nearly) the same y belong to one visual line
        if lines and abs(lines[-1][0][0] - box[0]) < 12:
            lines[-1].append(box)
        else:
            lines.append([box])
    return [" ".join(t for _, _, t in sorted(line, key=lambda b: b[1])) for line in lines], ms


def parse_winocr(path: Path) -> dict[str, tuple[list[str], float]]:
    out: dict[str, tuple[list[str], float]] = {}
    name = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if m := re.match(r"== (\S+) (\d+) ms", raw):
            name = m.group(1)
            out[name] = ([], float(m.group(2)))
        elif name and (m := re.match(r"\s+y=\d+ (.*)", raw)) and len(m.group(1).strip()) > 1:
            out[name][0].append(m.group(1).strip())
    return out


def names(line: str) -> set[str]:
    return {n for m in _NAME.finditer(line) for n in m.groups() if n}


def score(truth: dict[str, list[str]], results: dict[str, tuple[list[str], float]]) -> dict:
    sims, sims_nospace, exact, found, total_names, times = [], [], 0, 0, 0, []
    for crop, expected in truth.items():
        got, ms = results[crop]
        times.append(ms)
        text = " ".join(got)
        for line in expected:
            best = max(got, key=lambda g: Levenshtein.normalized_similarity(line, g), default="")
            sims.append(Levenshtein.normalized_similarity(line, best))
            sims_nospace.append(
                Levenshtein.normalized_similarity(line.replace(" ", ""), best.replace(" ", ""))
            )
            exact += " ".join(best.split()) == line
            for name in names(line):
                total_names += 1
                found += name in text
    lines = sum(len(v) for v in truth.values())
    return {
        "char": statistics.mean(sims),
        "char_nospace": statistics.mean(sims_nospace),
        "exact_lines": exact / lines,
        "names": found / total_names,
        "ms": statistics.median(times),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("crops", type=Path)
    parser.add_argument("truth", type=Path)
    parser.add_argument("--winocr", action="append", default=[], metavar="NAME=FILE")
    parser.add_argument("--rec", action="append", default=[], metavar="NAME=MODEL:DICT")
    parser.add_argument("--scales", default="1,1.5,2", help="upscale factors for RapidOCR")
    args = parser.parse_args()
    truth = json.loads(args.truth.read_text(encoding="utf-8"))

    from rapidocr_onnxruntime import RapidOCR

    one_thread = {"intra_op_num_threads": 1, "inter_op_num_threads": 1}  # as the app runs it
    models = {"RapidOCR": RapidOCR(**one_thread)}
    for spec in args.rec:
        label, files = spec.split("=", 1)
        model, keys = files.split(":", 1)
        models[label] = RapidOCR(rec_model_path=model, rec_keys_path=keys, **one_thread)
    engines = {}
    for label, engine in models.items():
        for scale in (float(s) for s in args.scales.split(",")):
            engines[f"{label} {scale:g}x"] = {
                crop: rapid_lines(engine, cv2.imread(str(args.crops / crop)), scale)
                for crop in truth
            }
    for spec in args.winocr:
        label, file = spec.split("=", 1)
        engines[label] = parse_winocr(Path(file))

    print("| Engine | Chars | Chars ignoring spaces | Exact lines | Names | ms/frame |")
    print("|---|---|---|---|---|---|")
    for label, results in engines.items():
        s = score(truth, results)
        print(f"| {label} | {s['char']:.1%} | {s['char_nospace']:.1%} | {s['exact_lines']:.0%} "
              f"| {s['names']:.0%} | {s['ms']:.0f} |")  # fmt: skip


if __name__ == "__main__":
    main()

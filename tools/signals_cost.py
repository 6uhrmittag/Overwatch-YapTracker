"""What do the match signals cost, in a match and between matches? (#453)

    python tools/signals_cost.py 2026-09-29_20-25-25 [2026-09-29_21-25-51 ...]

Replays the 1 fps full frames of fixtures/private/frames/<recording>/ through hero select and
the end screen, like the app's `on_signals` (one look a second, as the GDI source sends them).
Prints the share of one core in a match and between matches, the OCR reads, and the matches
found - so a change to the signals can be checked for cost and for the same matches.
--no-gate reads every look again, as before #453, to compare. Heavy (real OCR): run it
when nobody is playing.
"""

import argparse
import os
import tempfile
import time
from pathlib import Path

import cv2

from yaptracker import signals as sig
from yaptracker.matches import MatchTracker
from yaptracker.ocr.engine import RapidOcrEngine
from yaptracker.pause import Pause
from yaptracker.store.repo import Store

FRAMES = Path(__file__).resolve().parents[1] / "fixtures" / "private" / "frames"
T0 = 1_000_000.0


def replay(recording: str, ocr: RapidOcrEngine, gate: bool) -> None:
    root = FRAMES / recording
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        _replay(root, Store.open(Path(tmp) / "yaptracker.db", Path(tmp) / "backups"), ocr, gate)


def _replay(root: Path, store: Store, ocr: RapidOcrEngine, gate: bool) -> None:
    recording = root.name
    full = sorted(os.listdir(root / "full"), key=lambda name: int(name[:-4]))
    now = {"t": T0}
    tracker = MatchTracker(store, Pause(), clock=lambda: now["t"])
    reads = {"n": 0}

    def read_line(image):
        reads["n"] += 1
        return ocr.read_line(image)

    def read_lines(image):
        reads["n"] += 1
        return [line.text for line in ocr.read(image, accents=True)]  # like the app

    if gate:  # like the app since #453
        read_line = sig.SameLook(read_line)

    hero_select = sig.HeroSelect(
        read_line, read_lines,
        lambda mode, map_name: tracker.new_match(source="heroselect", mode=mode,
                                                 map_name=map_name),
        lambda: now["t"], match_running=lambda: tracker.running,
    )  # fmt: skip
    end_screen = sig.EndScreen(read_line, lambda outcome: tracker.end_match(outcome=outcome),
                               lambda: now["t"])  # fmt: skip
    regions = sig.signal_regions(2560, 1440)
    spent = {"in match": 0.0, "between matches": 0.0}
    seconds = dict.fromkeys(spent, 0)
    ocr_reads = dict.fromkeys(spent, 0)
    for name in full:
        now["t"] = T0 + int(name[:-4]) / 1000
        frame = cv2.imread(str(root / "full" / name))
        crops = {k: r.crop(frame).copy() for k, r in regions.items()}
        state = "in match" if tracker.running else "between matches"
        before, started = reads["n"], time.process_time()
        hero_select.update(crops)
        end_screen.update(crops)
        spent[state] += time.process_time() - started
        seconds[state] += 1
        ocr_reads[state] += reads["n"] - before
    reused = f", {read_line.reused} looks answered without a read" if gate else ""
    print(f"{recording} ({'gate' if gate else 'no gate'}{reused}):")
    for state in spent:
        if seconds[state]:
            print(f"  {state}: {100 * spent[state] / seconds[state]:5.2f} % of a core, "
                  f"{ocr_reads[state]} reads in {seconds[state]} s")  # fmt: skip
    print("  matches:", store._read("SELECT source, outcome, mode, map FROM matches"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("recordings", nargs="+", help="folder names under fixtures/private/frames")
    parser.add_argument("--no-gate", action="store_true", help="look at every region every time")
    args = parser.parse_args()
    ocr = RapidOcrEngine()
    ocr.read_line(cv2.imread(str(next((FRAMES / args.recordings[0] / "full").iterdir()))))
    for recording in args.recordings:
        replay(recording, ocr, gate=not args.no_gate)


if __name__ == "__main__":
    main()

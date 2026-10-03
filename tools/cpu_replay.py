"""How much CPU does YapTracker need during play? (#108, #115)

    python tools/cpu_replay.py 2026-09-29_20-25-25

Replays fixtures/private/frames/<recording>/ (from tools/extract_frames.py) through the whole
pipeline as the app runs it: change detection on every chat frame (4 fps), OCR -> parse ->
dedup -> store on the changed ones (at most one read per MIN_GAP_S, the newest frame waiting),
and once a second the match signals and debug overviews.
Prints the CPU share of one core per minute of footage; reading the images doesn't count.
After a minute above the CPU goal the next one reads every 3 s, like the app (#249);
--no-busy-gate leaves that out, to compare.

Heavy: real OCR on hundreds of frames. Run it when nobody is playing.
"""

import argparse
import os
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import cv2

from yaptracker.capture.changes import ChangeDetector
from yaptracker.debug import DebugSamples
from yaptracker.matches import MatchTracker
from yaptracker.ocr.engine import RapidOcrEngine
from yaptracker.pause import Pause
from yaptracker.reader import BUSY_GAP_S, CPU_GOAL, MIN_GAP_S, ChatReader
from yaptracker.signals import EndScreen, HeroSelect, signal_regions
from yaptracker.store.repo import Store

FRAMES = Path(__file__).resolve().parents[1] / "fixtures" / "private" / "frames"
T0 = 1_000_000.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("recording", help="folder name under fixtures/private/frames")
    parser.add_argument("--no-busy-gate", action="store_true",
                        help="read every 1.5 s even after a minute above the CPU goal")  # fmt: skip
    args = parser.parse_args()
    root = FRAMES / args.recording
    chat = sorted(os.listdir(root / "chat"))
    full = {int(name[:-4]) // 1000: name for name in os.listdir(root / "full")}
    tmp = Path(tempfile.mkdtemp())
    store = Store.open(tmp / "yaptracker.db", tmp / "backups")
    now = {"t": T0}

    def clock() -> float:
        return now["t"]

    tracker = MatchTracker(store, Pause(), clock=clock)
    ocr = RapidOcrEngine()

    reader = ChatReader(ocr.read, store, tracker, clock=clock)
    changes = ChangeDetector()
    hero_select = HeroSelect(
        ocr.read_line,
        lambda image: [line.text for line in ocr.read(image)],
        lambda mode, map_name: tracker.new_match(source="heroselect", mode=mode,
                                                 map_name=map_name),
        clock,
        match_running=lambda: tracker.running,
    )  # fmt: skip
    end_screen = EndScreen(ocr.read_line, lambda outcome: tracker.end_match(outcome=outcome), clock)
    debug = DebugSamples(tmp / "debug", lambda: True, clock)
    regions = signal_regions(2560, 1440)
    cpu: dict[int, float] = defaultdict(float)
    reads: dict[int, int] = defaultdict(int)
    ocr.read(cv2.imread(str(root / "chat" / chat[0])))  # loading the models isn't play time
    last_second, last_read, pending = -1, float("-inf"), None
    for name in chat:
        t = int(name[:-4]) / 1000
        now["t"], minute = T0 + t, int(t // 60)
        busy = not args.no_busy_gate and 100 * cpu.get(minute - 1, 0.0) / 60 > CPU_GOAL
        image = cv2.imread(str(root / "chat" / name))
        started = time.process_time()
        tracker.capture_alive()
        changed = changes.update(image)
        if changed or reader.wants_reread():  # weak lines are read again (#195), like the app
            pending = image  # the newest change waits for the gap, like the reader thread
        if pending is not None and t - last_read >= (BUSY_GAP_S if busy else MIN_GAP_S):
            reader.read_frame(now["t"], pending)
            pending, last_read = None, t
            reads[minute] += 1
        cpu[minute] += time.process_time() - started
        second = int(t)
        if second != last_second and second in full:
            last_second = second
            frame = cv2.imread(str(root / "full" / full[second]))
            started = time.process_time()
            signals = {k: r.crop(frame).copy() for k, r in regions.items()}
            if second % 5 == 0:
                signals["overview"] = frame[::4, ::4].copy()
            debug.on_signals(signals)
            hero_select.update(signals)
            end_screen.update(signals)
            cpu[minute] += time.process_time() - started
    for minute in sorted(cpu):
        print(f"{minute:3d} min: {100 * cpu[minute] / 60:5.1f} % of a core, "
              f"{reads[minute]:3d} chat reads")  # fmt: skip

    def share(minutes: list[int]) -> float:
        return 100 * sum(cpu[m] for m in minutes) / (60 * len(minutes)) if minutes else 0.0

    busy = [m for m in cpu if reads[m] >= 30]
    quiet = [m for m in cpu if reads[m] <= 10]
    print(f"average {share(list(cpu)):.1f} %, busy minutes {share(busy):.1f} %, "
          f"quiet minutes {share(quiet):.1f} %")  # fmt: skip
    print(f"{store.stats().messages} yaps stored, matches:",
          store._read("SELECT source, outcome, map FROM matches"))  # fmt: skip


if __name__ == "__main__":
    main()

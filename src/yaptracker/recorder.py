"""The chat recorder (#654): one evening of the chat box, for measuring how many lines get lost.

Missed lines were fixed many times and came back each time, because nothing counted "lines that
were on screen" against "lines stored". A recording is the input for that count: every changed
chat-box frame (the change detector decides, as for reading) as a lossless WebP, an index line
for every frame (changed or not, so a replay sees what the detector skipped), and the match
signal crops once a second. Off by default; switched on, it records for RECORD_S and then
switches itself off.

data\\recordings\\<date>\\<HH-MM-SS>\\ (one folder per start): chat\\<ms>.webp,
signals\\<ms>-<name>.webp and frames.jsonl. Not under debug\\: the debug samples' 1 GB cap
would delete a recording
mid-evening. Kept 14 days. Real names are in there: never committed, never uploaded.

The capture thread only queues: a writer thread encodes. When it falls behind, frames are
dropped and counted in the index, never waited for.
"""

import json
import logging
import queue
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from yaptracker import images, side_work
from yaptracker.debug import free_bytes

log = logging.getLogger(__name__)

RECORD_S = 12 * 3600  # one evening: then it switches itself off
KEEP_DAYS = 14
SIGNALS_EVERY_S = 1.0
LOW_DISK_BYTES = 5_000_000_000  # less free than this: recording pauses (a real 4K chat frame is
# ~0.8 MB lossless, ~25-30 changed frames a minute: about 1.5 GB an hour)
DISK_CHECK_S = 60.0
QUEUE = 64  # pictures waiting for the writer; more and the newest is dropped (and counted)
LOSSLESS = [cv2.IMWRITE_WEBP_QUALITY, 101]  # > 100: lossless


def folder_bytes(folder: Path) -> int:
    if not folder.exists():
        return 0
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())


class ChatRecorder:
    def __init__(
        self,
        folder: Path,
        until: Callable[[], float],
        stop: Callable[[], object] = lambda: None,
        clock: Callable[[], float] = time.time,
        keep_days: int = KEEP_DAYS,
        free: Callable[[Path], int] = free_bytes,
    ) -> None:
        """until(): the time recording ends (0: off). stop(): called once when it ran out."""
        self._folder, self._until, self._stop, self._clock = folder, until, stop, clock
        self._keep_days, self._free = keep_days, free
        self._low, self._disk_checked = False, -float("inf")
        self._queue: queue.Queue = queue.Queue(maxsize=QUEUE)
        self._run: Path | None = None  # this start's folder, made with the first frame
        self._signals_at = 0.0
        self._dropped = 0
        self._bytes = 0  # written since the start, added to the folder's size at start
        self._counted: int | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.frames = 0

    def on(self) -> bool:
        until = self._until()
        if not until:
            return False
        if self._clock() < until:
            return not self._disk_low()
        log.info("chat recorder: the evening is over, recording switched off")
        self._stop()
        return False

    def _disk_low(self) -> bool:
        """Less than LOW_DISK_BYTES free: paused, said in the log when it changes."""
        now = self._clock()
        if now - self._disk_checked < DISK_CHECK_S:
            return self._low
        self._disk_checked = now
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            low = self._free(self._folder) < LOW_DISK_BYTES
        except OSError:
            return self._low
        if low != self._low:
            log.warning("chat recorder: %s", "paused, less than 5 GB free" if low else
                        "recording again, the disk has space")  # fmt: skip
        self._low = low
        return low

    def start(self) -> None:
        """Old recordings cleaned up, the folder counted, the writer started: in the background."""
        self._thread = threading.Thread(target=self._write, name="chat recorder", daemon=True)
        self._thread.start()

    def frame(self, image: np.ndarray, changed: bool, **seen) -> None:
        """From the capture thread: every chat frame. Saved when changed; the index has all.
        `seen`: what else to keep with it (match, reading mode). Never blocks."""
        if not self.on():
            return
        ms = int(self._clock() * 1000)
        entry = {"ms": ms, "changed": changed, **seen}
        picture = None
        if changed:
            picture = f"chat/{ms}.webp"
            entry["picture"] = picture
        self._put(entry, picture, image if changed else None)

    def signals(self, crops: dict[str, np.ndarray]) -> None:
        """From the capture thread, about once a second: the match signal crops."""
        if not self.on():
            return
        now = self._clock()
        if now - self._signals_at < SIGNALS_EVERY_S:
            return
        self._signals_at = now
        ms = int(now * 1000)
        for name, crop in crops.items():
            if name == "overview" or crop is None or not getattr(crop, "size", 0):
                continue
            self._put(None, f"signals/{ms}-{name}.webp", crop)

    def _put(self, entry: dict | None, picture: str | None, image: np.ndarray | None) -> None:
        if self._dropped and entry is not None:
            entry["dropped_before"], self._dropped = self._dropped, 0
        try:
            self._queue.put_nowait((entry, picture, None if image is None else image.copy()))
        except queue.Full:  # chat frames are counted (the index says so); signal crops not
            if entry is not None:
                self._dropped = entry.pop("dropped_before", 0) + 1

    def _folder_now(self) -> Path:
        if self._run is None:
            now = self._clock()
            day = time.strftime("%Y-%m-%d", time.localtime(now))
            self._run = self._folder / day / time.strftime("%H-%M-%S", time.localtime(now))
            (self._run / "chat").mkdir(parents=True, exist_ok=True)
            (self._run / "signals").mkdir(exist_ok=True)
            log.info("chat recorder: recording into %s", self._run)
        return self._run

    def _write(self) -> None:
        self._clean_up()
        with self._lock:
            self._counted = folder_bytes(self._folder)
        while True:
            entry, picture, image = self._queue.get()
            if entry is None and picture is None:
                return  # stop()
            try:
                run = self._folder_now()
                if image is not None and picture is not None:
                    path = run / picture
                    images.write(path, image, LOSSLESS)
                    with self._lock:
                        self._bytes += path.stat().st_size
                if entry is not None:
                    with (run / "frames.jsonl").open("a", encoding="utf-8") as index:
                        index.write(json.dumps(entry) + "\n")
                    self.frames += 1
            except Exception as error:  # a full disk, a removed folder: the evening goes on
                side_work.failed("recording the chat", error, then="it goes on")

    def close(self) -> None:
        """At quit: what's queued is written, then the writer ends."""
        if self._thread is None:
            return
        try:
            self._queue.put((None, None, None), timeout=5)
        except queue.Full:
            return
        self._thread.join(timeout=10)

    stop = close  # with the other parts at quit

    def size_bytes(self) -> int | None:
        """None while it's still being counted at start."""
        with self._lock:
            return None if self._counted is None else self._counted + self._bytes

    def _clean_up(self) -> None:
        """Day folders older than KEEP_DAYS go."""
        if not self._folder.exists():
            return
        oldest_kept = time.strftime(
            "%Y-%m-%d", time.localtime(self._clock() - self._keep_days * 86400)
        )
        for day in sorted(p for p in self._folder.iterdir() if p.is_dir()):
            if day.name < oldest_kept:
                shutil.rmtree(day, ignore_errors=True)
                log.info("chat recorder: recording of %s deleted (older than %d days)", day.name,
                         self._keep_days)  # fmt: skip

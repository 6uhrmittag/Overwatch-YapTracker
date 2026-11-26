"""The chat recorder (#654): one evening of the chat box, for measuring how many lines get lost.

Missed lines were fixed many times and came back each time, because nothing counted "lines that
were on screen" against "lines stored". A recording is the input for that count: every changed
chat-box frame (the change detector decides, as for reading) as a lossless PNG, an index line
for every frame (changed or not, so a replay sees what the detector skipped), and the match
signal crops once a second. Off by default; switched on, it records for RECORD_S and then
switches itself off.

data\\recordings\\<date>\\<HH-MM-SS>\\ (one folder per switch-on): chat\\<ms>.png,
signals\\<ms>-<name>.png and frames.jsonl. Not under debug\\: the debug samples' 1 GB cap
would delete a recording mid-evening. Kept 14 days and 30 GB at most. Real names are in there:
never committed, never uploaded.

The capture thread only queues: a writer thread encodes. When it falls behind, frames are
dropped and counted in the index, never waited for.
"""

import contextlib
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
LOW_DISK_BYTES = 5_000_000_000  # less free than this: recording pauses
CAP_BYTES = 30_000_000_000  # all recordings together: the oldest days go at start, then it pauses
DISK_CHECK_S = 60.0
UNTIL_CHECK_S = 5.0  # the setting is read this often, not on every frame
QUEUE = 64  # pictures waiting for the writer; more and the newest is dropped (and counted)
# PNG, fastest compression: lossless WebP of a real 4K chat frame took 678 ms of CPU (about a
# third of a core at 25-30 changed frames a minute, against the game), PNG level 1 74 ms for
# 1.2 MB instead of 0.8 MB: about 2 GB an hour.
PICTURE, ENCODE = ".png", [cv2.IMWRITE_PNG_COMPRESSION, 1]


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
        cap_bytes: int = CAP_BYTES,
    ) -> None:
        """until(): the time recording ends (0: off). stop(): called once when it ran out."""
        self._folder, self._until, self._stop, self._clock = folder, until, stop, clock
        self._keep_days, self._free, self._cap = keep_days, free, cap_bytes
        self._low, self._disk_checked = False, -float("inf")
        self._full = False  # above the cap: said once
        self._until_at, self._until_read = 0.0, -float("inf")  # the setting, read every 5 s
        self._was_on = False
        # one recording per switch-on, named by when (also within one app run): (number, time)
        self._gen: tuple[int, float] = (0, 0.0)
        self._queue: queue.Queue = queue.Queue(maxsize=QUEUE)
        self._run: tuple[tuple, Path] | None = None  # (gen, folder) of the recording written
        self._signals_at = 0.0
        self._dropped = self._dropped_signals = 0
        self._bytes = 0  # written since the start, added to the folder's size at start
        self._counted: int | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.frames = 0

    def refresh(self) -> None:
        """The setting was changed (Settings): read it at the next frame."""
        self._until_read = -float("inf")

    def on(self) -> bool:
        now = self._clock()
        if now - self._until_read >= UNTIL_CHECK_S:
            self._until_at, self._until_read = self._until(), now
        until = self._until_at
        if until and now >= until:
            log.info("chat recorder: the evening is over, recording switched off")
            self._until_at = 0.0
            self._stop()
        recording = bool(self._until_at) and not self._disk_low() and not self._too_big()
        if recording and not self._was_on:
            self._gen = (self._gen[0] + 1, now)
        self._was_on = recording
        return recording

    def _too_big(self) -> bool:
        size = self.size_bytes()
        full = size is not None and size > self._cap
        if full and not self._full:
            log.warning(
                "chat recorder: paused, recordings take more than %d GB", self._cap // 10**9
            )
        self._full = full
        return full

    def _disk_low(self) -> bool:
        """Less than LOW_DISK_BYTES free: paused, said in the log when it changes."""
        now = self._clock()
        if now - self._disk_checked < DISK_CHECK_S:
            return self._low
        self._disk_checked = now
        try:
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
            picture = f"chat/{ms}{PICTURE}"
            entry["picture"] = picture
        if self._dropped_signals:
            entry["signals_dropped_before"], self._dropped_signals = self._dropped_signals, 0
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
            self._put(None, f"signals/{ms}-{name}{PICTURE}", crop)

    def _put(self, entry: dict | None, picture: str | None, image: np.ndarray | None) -> None:
        if self._dropped and entry is not None:
            entry["dropped_before"], self._dropped = self._dropped, 0
        item = (self._gen, entry, picture, None if image is None else image.copy())
        try:
            self._queue.put_nowait(item)
        except queue.Full:  # counted: the next index line says how many were lost
            if entry is None:
                self._dropped_signals += 1
            else:
                self._dropped = entry.pop("dropped_before", 0) + 1
                self._dropped_signals += entry.pop("signals_dropped_before", 0)

    def _folder_now(self, gen: tuple[int, float]) -> Path:
        if self._run is None or self._run[0] != gen:
            at = time.localtime(gen[1])
            run = self._folder / time.strftime("%Y-%m-%d", at) / time.strftime("%H-%M-%S", at)
            (run / "chat").mkdir(parents=True, exist_ok=True)
            (run / "signals").mkdir(exist_ok=True)
            self._run = (gen, run)
            log.info("chat recorder: recording into %s", run)
        return self._run[1]

    def _write(self) -> None:
        try:
            self._clean_up()
            counted = folder_bytes(self._folder)
        except Exception as error:  # a locked or vanished file: recording still works
            side_work.failed("counting the chat recordings", error, then="it goes on")
            counted = 0
        with self._lock:
            self._counted = counted
        while True:
            gen, entry, picture, image = self._queue.get()
            if entry is None and picture is None:
                return  # stop()
            try:
                run = self._folder_now(gen)
                if image is not None and picture is not None:
                    path = run / picture
                    images.write(path, image, ENCODE)
                    with self._lock:
                        self._bytes += path.stat().st_size
                if entry is not None:
                    with (run / "frames.jsonl").open("a", encoding="utf-8") as index:
                        index.write(json.dumps(entry) + "\n")
                    self.frames += 1
            except Exception as error:  # a full disk, a removed folder: the evening goes on
                side_work.failed("recording the chat", error, then="it goes on")

    def close(self) -> None:
        """At quit: what's queued is written (and what was dropped, counted), then the writer
        ends."""
        if self._thread is None:
            return
        if (self._dropped or self._dropped_signals) and self._run is not None:
            last = {"ms": int(self._clock() * 1000), "end": True,
                    "dropped_before": self._dropped,
                    "signals_dropped_before": self._dropped_signals}  # fmt: skip
            with contextlib.suppress(queue.Full):
                self._queue.put((self._gen, last, None, None), timeout=5)
        try:
            self._queue.put((self._gen, None, None, None), timeout=5)
        except queue.Full:
            log.warning("chat recorder: quitting with %d pictures not written",
                        self._queue.qsize())  # fmt: skip
            return
        self._thread.join(timeout=10)

    stop = close  # with the other parts at quit

    def size_bytes(self) -> int | None:
        """None while it's still being counted at start."""
        with self._lock:
            return None if self._counted is None else self._counted + self._bytes

    def _clean_up(self) -> None:
        """Day folders older than KEEP_DAYS go, then the oldest days while above the cap."""
        if not self._folder.exists():
            return
        oldest_kept = time.strftime(
            "%Y-%m-%d", time.localtime(self._clock() - self._keep_days * 86400)
        )
        days = sorted(p for p in self._folder.iterdir() if p.is_dir())
        sizes = {day: folder_bytes(day) for day in days}
        total = sum(sizes.values())
        for day in days:
            old = day.name < oldest_kept
            if not old and total <= self._cap:
                break
            shutil.rmtree(day, ignore_errors=True)
            total -= sizes[day]
            why = f"older than {self._keep_days} days" if old else "above the size cap"
            log.info("chat recorder: recording of %s deleted (%s)", day.name, why)

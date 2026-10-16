"""Debug samples (#63, #110): YapTracker keeps the moments it found hard, so they become tests.

data\\debug\\<date>\\<time>-<what>\\ holds JPEG overview frames (every 4th pixel of the game
window) and the PNG signal crops the detectors read, or (`-chat`) the chat frames of the last
20 s with what OCR and the parser made of them (sample.json). Real names are in there: like
fixtures/private/, never committed and never uploaded (YapTracker is local-only anyway).
At most 1 GB and 14 days, the oldest samples go first. Nothing is kept while paused, nor while
the disk has less than 1 GB free (#452); hand corrections are still kept then.
"""

import json
import logging
import math
import shutil
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from yaptracker import images, side_work
from yaptracker.sizes import FolderSizes

log = logging.getLogger(__name__)

# A missed end screen only shows when the next match starts (hero select, or chat after the
# 5-minute gap), so the overview frames of the last few minutes are kept to look back at it.
BUFFER_S = 6 * 60
CAP_BYTES = 1_000_000_000
KEEP_DAYS = 14
CHAT_CONTEXT_S = 20.0  # chat frames kept for a chat sample: enough to see a line arrive and fade
CHAT_SAMPLE_EVERY_S = 60.0  # automatic chat samples at most once a minute
LOW_CONFIDENCE = 0.85
LOW_DISK_BYTES = 1_000_000_000  # less free space than this: samples pause (#452)
DISK_LOW_SAY = ("Disk almost full: debug samples paused. Chat is still saved. Free up some space "
                "and they start again by themselves.")  # fmt: skip
DISK_CHECK_S = 60.0


def why_hard(lines, new, unstored=()) -> list[str]:
    """Why a read chat frame is worth keeping; empty if it isn't (#110)."""
    reasons = {"seen-not-stored"} if unstored else set()  # (#425)
    for line in lines:  # map text behind the chat is unknown too, so: only chat-looking lines
        if line.kind == "unknown" and any(c in line.text for c in "[]:("):
            reasons.add("unparsed")
    for yap in new:
        if yap.best.confidence < LOW_CONFIDENCE:
            reasons.add("low-confidence")
        if yap.best.kind == "message" and yap.best.channel == "unknown":
            reasons.add("channel-unknown")
    return sorted(reasons)


def folder_size(folder: Path) -> int:
    if not folder.exists():
        return 0
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())


def free_bytes(folder: Path) -> int:
    """Free space on the drive of the folder (or of its nearest existing parent)."""
    while not folder.exists() and folder.parent != folder:
        folder = folder.parent
    return shutil.disk_usage(folder).free


def samples_in(folder: Path) -> list[tuple[Path, int]]:
    """The one walk at start (#387): each sample folder (in its day folder) with its size, and
    each loose file (corrections, things put there by hand)."""
    found: list[tuple[Path, int]] = []
    if not folder.exists():
        return found
    for top in folder.iterdir():
        if top.is_file():
            found.append((top, top.stat().st_size))
            continue
        for item in top.iterdir():
            found.append((item, folder_size(item) if item.is_dir() else item.stat().st_size))
    return found


class DebugSamples:
    def __init__(
        self,
        folder: Path,
        enabled: Callable[[], bool],
        clock: Callable[[], float] = time.time,
        buffer_s: float = BUFFER_S,
        cap_bytes: int = CAP_BYTES,
        keep_days: int = KEEP_DAYS,
        free: Callable[[Path], int] = free_bytes,
    ) -> None:
        self._folder, self._enabled, self._clock, self._free = folder, enabled, clock, free
        self._low = False  # paused for a nearly full disk (#452); Live says so
        self._disk_checked = -math.inf
        self._buffer_s, self._cap_bytes, self._keep_days = buffer_s, cap_bytes, keep_days
        self._lock = threading.Lock()
        self._overviews: deque[tuple[float, bytes]] = deque()
        self._signals: dict[str, np.ndarray] = {}
        self._chat: deque[tuple[float, np.ndarray, list, list]] = deque()
        self._chat_sampled_at = -math.inf
        self._cleaning = threading.Lock()
        self.sizes = FolderSizes()  # counted once, then kept up to date (#387)

    def _active(self) -> bool:
        return self._enabled() and not self.disk_low()

    def disk_low(self) -> bool:
        """Less than 1 GB free: samples pause (#452). The disk is looked at once a minute, also
        when asked by Live; the log says when samples pause and start again."""
        now = self._clock()
        if now - self._disk_checked < DISK_CHECK_S:
            return self._low
        self._disk_checked = now
        try:
            low = self._free(self._folder) < LOW_DISK_BYTES
        except OSError:
            return self._low
        if low != self._low:
            if low:
                log.warning("Disk almost full: debug samples paused (less than 1 GB free)")
            else:
                log.info("Disk has space again: debug samples back on")
        self._low = low
        return low

    def on_signals(self, signals: dict[str, np.ndarray], paused: bool = False) -> None:
        """About once a second from the capture thread: signal crops, every few s an overview."""
        if paused or not self._active():
            with self._lock:
                self._overviews.clear()
                self._signals = {}
                self._chat.clear()
            return
        now = self._clock()
        overview = signals.get("overview")
        jpg = None
        if overview is not None:
            ok, encoded = cv2.imencode(".jpg", overview, [cv2.IMWRITE_JPEG_QUALITY, 80])
            jpg = encoded.tobytes() if ok else None
        with self._lock:
            self._signals = {k: v for k, v in signals.items() if k != "overview"}
            if jpg is not None:
                self._overviews.append((now, jpg))
            while self._overviews and now - self._overviews[0][0] > self._buffer_s:
                self._overviews.popleft()

    def match_event(self, what: str) -> Path | None:
        """'start' / 'end' / 'end-map' (#383): the newest overview and crops. 'missed-end' and
        'missed-start-…' (#170): every buffered overview, to look back at what the detection
        didn't see."""
        if not self._active():
            return None
        with self._lock:
            overviews = list(self._overviews)
            signals = dict(self._signals)
        if not what.startswith("missed"):
            overviews = overviews[-1:]
        if not overviews and not signals:
            return None
        try:  # from the capture thread: a full disk must not stop the capture (#452)
            return self._save_event(what, overviews, signals)
        except Exception as error:
            side_work.failed("saving a debug sample", error)
            return None

    def _save_event(self, what: str, overviews: list, signals: dict) -> Path:
        now = time.localtime(self._clock())
        sample = self._folder / time.strftime("%Y-%m-%d", now)
        sample /= f"{time.strftime('%H-%M-%S', now)}-{what}"
        sample.mkdir(parents=True, exist_ok=True)
        for ts, jpg in overviews:
            (sample / f"{time.strftime('%H-%M-%S', time.localtime(ts))}.jpg").write_bytes(jpg)
        for name, crop in signals.items():
            images.write(sample / f"{name}.png", crop)
        self.sizes.set(sample, folder_size(sample))
        self.clean_up()
        return sample

    def chat_read(
        self, ts: float, image: np.ndarray, ocr: list, lines: list, new: list, unstored=()
    ) -> Path | None:
        """Every chat frame the reader read (#108): kept 20 s; hard ones become a sample."""
        if not self._active():
            return None
        with self._lock:
            self._chat.append((ts, image, ocr, lines))
            while self._chat and ts - self._chat[0][0] > CHAT_CONTEXT_S:
                self._chat.popleft()
            reasons = why_hard(lines, new, unstored)
            if not reasons or ts - self._chat_sampled_at < CHAT_SAMPLE_EVERY_S:
                return None
            self._chat_sampled_at = ts
        return self.save_chat(",".join(reasons))

    def save_chat(self, why: str = "hotkey") -> Path | None:
        """The last 20 s of read chat frames, with their OCR and parse results (Ctrl+Alt+S)."""
        if not self._active():
            return None
        with self._lock:
            frames = list(self._chat)
        if not frames:
            return None
        try:
            return self._save_chat(why, frames)
        except Exception as error:  # a full disk: the chat line is stored all the same (#452)
            side_work.failed("saving a debug sample", error)
            return None

    def _save_chat(self, why: str, frames: list) -> Path:
        now = time.localtime(self._clock())
        sample = self._folder / time.strftime("%Y-%m-%d", now)
        sample /= f"{time.strftime('%H-%M-%S', now)}-chat"
        sample.mkdir(parents=True, exist_ok=True)
        records = []
        for n, (ts, image, ocr, lines) in enumerate(frames):
            last = n == len(frames) - 1  # the hard one: lossless, the context as JPEG
            name = f"{n:02d}-{time.strftime('%H-%M-%S', time.localtime(ts))}"
            name += ".png" if last else ".jpg"
            images.write(sample / name, image, [] if last else [cv2.IMWRITE_JPEG_QUALITY, 90])
            records.append({
                "t": ts,
                "image": name,
                "ocr": [{"text": o.text, "confidence": round(o.confidence, 3),
                         "box": [o.box.x, o.box.y, o.box.width, o.box.height]} for o in ocr],
                "parsed": [{"kind": c.kind, "channel": c.channel, "speaker": c.speaker,
                            "text": c.text, "confidence": round(c.confidence, 3)} for c in lines],
            })  # fmt: skip
        sample_json = {"why": why, "frames": records}
        (sample / "sample.json").write_text(
            json.dumps(sample_json, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        self.sizes.set(sample, folder_size(sample))
        self.clean_up()
        return sample

    def correction(self, message, text: str, picture: Path | None) -> Path | None:
        """A line fixed by hand (#227): what OCR read, what it really says, and its picture.
        Plain files in debug/corrections/, so the day/size clean-up leaves them alone: they're
        hand-checked ground truth for the next OCR change."""
        if not self._enabled():  # tiny and rare: kept also on a nearly full disk
            return None
        try:
            return self._save_correction(message, text, picture)
        except Exception as error:  # the fixed line is saved all the same (#452)
            side_work.failed("saving a correction sample", error)
            return None

    def _save_correction(self, message, text: str, picture: Path | None) -> Path:
        folder = self._folder / "corrections"
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{time.strftime('%Y-%m-%d-%H%M%S', time.localtime(message.ts))}-{message.id}"
        record = {"id": message.id, "ts": message.ts, "channel": message.channel,
                  "speaker": message.speaker_raw, "ocr": message.original_text or message.text,
                  "fixed": text}  # fmt: skip
        target = folder / f"{stem}.json"
        target.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        self.sizes.set(target, target.stat().st_size)
        if picture is not None and picture.exists():
            copy = Path(shutil.copy(picture, folder / f"{stem}{picture.suffix}"))
            self.sizes.set(copy, copy.stat().st_size)
        return target

    def channel_correction(self, message, channel: str, picture: Path | None) -> Path | None:
        """A line's channel fixed by hand (#283): ground truth for the icon/colour check
        (#173, #228), next to the text corrections."""
        if not self._enabled():
            return None
        try:
            return self._save_channel_correction(message, channel, picture)
        except Exception as error:
            side_work.failed("saving a correction sample", error)
            return None

    def _save_channel_correction(self, message, channel: str, picture: Path | None) -> Path:
        folder = self._folder / "corrections"
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{time.strftime('%Y-%m-%d-%H%M%S', time.localtime(message.ts))}-{message.id}-ch"
        record = {"id": message.id, "ts": message.ts, "speaker": message.speaker_raw,
                  "text": message.text, "ocr_channel": message.channel,
                  "fixed_channel": channel}  # fmt: skip
        target = folder / f"{stem}.json"
        target.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        self.sizes.set(target, target.stat().st_size)
        if picture is not None and picture.exists():
            copy = Path(shutil.copy(picture, folder / f"{stem}{picture.suffix}"))
            self.sizes.set(copy, copy.stat().st_size)
        return target

    def start(self, background: bool = True) -> None:
        """At start: count the folder once in the background, then clean up."""
        self.sizes.count(lambda: samples_in(self._folder), self.clean_up, background)

    def clean_up(self) -> None:
        """Day folders older than 14 days go, then the oldest samples until under the cap.
        Sizes come from the running tally, never from walking (#387); not before it's counted."""
        if not self.sizes.ready.is_set() or not self._folder.exists():
            return
        with self._cleaning:
            oldest_kept = time.strftime(
                "%Y-%m-%d", time.localtime(self._clock() - self._keep_days * 86400)
            )
            days = sorted(p for p in self._folder.iterdir() if p.is_dir())
            for day in days:
                if day.name < oldest_kept:
                    shutil.rmtree(day, ignore_errors=True)
                    self.sizes.drop(day)
            samples = sorted(s for d in days if d.exists() for s in d.iterdir() if s.is_dir())
            sizes = self.sizes.snapshot()
            total = sum(sizes.get(sample, 0) for sample in samples)
            for sample in samples:  # names sort by date, then time
                if total <= self._cap_bytes:
                    break
                shutil.rmtree(sample, ignore_errors=True)
                total -= self.sizes.drop(sample)
            for day in days:
                if day.exists() and not any(day.iterdir()):
                    day.rmdir()

    def size_bytes(self) -> int | None:
        """None while it's still being counted at start."""
        return self.sizes.total()

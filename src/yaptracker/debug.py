"""Debug samples (#63, #110): YapTracker keeps the moments it found hard, so they become tests.

data\\debug\\<date>\\<time>-<what>\\ holds JPEG overview frames (every 4th pixel of the game
window) and the PNG signal crops the detectors read, or (`-chat`) the chat frames of the last
20 s with what OCR and the parser made of them (sample.json). Real names are in there: like
fixtures/private/, never committed and never uploaded (YapTracker is local-only anyway).
At most 1 GB and 14 days, the oldest samples go first. Nothing is kept while paused.
"""

import json
import math
import shutil
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

# A missed end screen only shows when the next match starts (hero select, or chat after the
# 5-minute gap), so the overview frames of the last few minutes are kept to look back at it.
BUFFER_S = 6 * 60
CAP_BYTES = 1_000_000_000
KEEP_DAYS = 14
CHAT_CONTEXT_S = 20.0  # chat frames kept for a chat sample: enough to see a line arrive and fade
CHAT_SAMPLE_EVERY_S = 60.0  # automatic chat samples at most once a minute
LOW_CONFIDENCE = 0.85


def why_hard(lines, new) -> list[str]:
    """Why a read chat frame is worth keeping; empty if it isn't (#110)."""
    reasons = set()
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


class DebugSamples:
    def __init__(
        self,
        folder: Path,
        enabled: Callable[[], bool],
        clock: Callable[[], float] = time.time,
        buffer_s: float = BUFFER_S,
        cap_bytes: int = CAP_BYTES,
        keep_days: int = KEEP_DAYS,
    ) -> None:
        self._folder, self._enabled, self._clock = folder, enabled, clock
        self._buffer_s, self._cap_bytes, self._keep_days = buffer_s, cap_bytes, keep_days
        self._lock = threading.Lock()
        self._overviews: deque[tuple[float, bytes]] = deque()
        self._signals: dict[str, np.ndarray] = {}
        self._chat: deque[tuple[float, np.ndarray, list, list]] = deque()
        self._chat_sampled_at = -math.inf

    def on_signals(self, signals: dict[str, np.ndarray], paused: bool = False) -> None:
        """About once a second from the capture thread: signal crops, every few s an overview."""
        if paused or not self._enabled():
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
        if not self._enabled():
            return None
        with self._lock:
            overviews = list(self._overviews)
            signals = dict(self._signals)
        if not what.startswith("missed"):
            overviews = overviews[-1:]
        if not overviews and not signals:
            return None
        now = time.localtime(self._clock())
        sample = self._folder / time.strftime("%Y-%m-%d", now)
        sample /= f"{time.strftime('%H-%M-%S', now)}-{what}"
        sample.mkdir(parents=True, exist_ok=True)
        for ts, jpg in overviews:
            (sample / f"{time.strftime('%H-%M-%S', time.localtime(ts))}.jpg").write_bytes(jpg)
        for name, crop in signals.items():
            cv2.imwrite(str(sample / f"{name}.png"), crop)
        self.clean_up()
        return sample

    def chat_read(
        self, ts: float, image: np.ndarray, ocr: list, lines: list, new: list
    ) -> Path | None:
        """Every chat frame the reader read (#108): kept 20 s; hard ones become a sample."""
        if not self._enabled():
            return None
        with self._lock:
            self._chat.append((ts, image, ocr, lines))
            while self._chat and ts - self._chat[0][0] > CHAT_CONTEXT_S:
                self._chat.popleft()
            reasons = why_hard(lines, new)
            if not reasons or ts - self._chat_sampled_at < CHAT_SAMPLE_EVERY_S:
                return None
            self._chat_sampled_at = ts
        return self.save_chat(",".join(reasons))

    def save_chat(self, why: str = "hotkey") -> Path | None:
        """The last 20 s of read chat frames, with their OCR and parse results (Ctrl+Alt+S)."""
        if not self._enabled():
            return None
        with self._lock:
            frames = list(self._chat)
        if not frames:
            return None
        now = time.localtime(self._clock())
        sample = self._folder / time.strftime("%Y-%m-%d", now)
        sample /= f"{time.strftime('%H-%M-%S', now)}-chat"
        sample.mkdir(parents=True, exist_ok=True)
        records = []
        for n, (ts, image, ocr, lines) in enumerate(frames):
            last = n == len(frames) - 1  # the hard one: lossless, the context as JPEG
            name = f"{n:02d}-{time.strftime('%H-%M-%S', time.localtime(ts))}"
            name += ".png" if last else ".jpg"
            cv2.imwrite(str(sample / name), image, [] if last else [cv2.IMWRITE_JPEG_QUALITY, 90])
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
        self.clean_up()
        return sample

    def correction(self, message, text: str, picture: Path | None) -> Path | None:
        """A line fixed by hand (#227): what OCR read, what it really says, and its picture.
        Plain files in debug/corrections/, so the day/size clean-up leaves them alone: they're
        hand-checked ground truth for the next OCR change."""
        if not self._enabled():
            return None
        folder = self._folder / "corrections"
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{time.strftime('%Y-%m-%d-%H%M%S', time.localtime(message.ts))}-{message.id}"
        record = {"id": message.id, "ts": message.ts, "channel": message.channel,
                  "speaker": message.speaker_raw, "ocr": message.original_text or message.text,
                  "fixed": text}  # fmt: skip
        target = folder / f"{stem}.json"
        target.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        if picture is not None and picture.exists():
            shutil.copy(picture, folder / f"{stem}{picture.suffix}")
        return target

    def channel_correction(self, message, channel: str, picture: Path | None) -> Path | None:
        """A line's channel fixed by hand (#283): ground truth for the icon/colour check
        (#173, #228), next to the text corrections."""
        if not self._enabled():
            return None
        folder = self._folder / "corrections"
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{time.strftime('%Y-%m-%d-%H%M%S', time.localtime(message.ts))}-{message.id}-ch"
        record = {"id": message.id, "ts": message.ts, "speaker": message.speaker_raw,
                  "text": message.text, "ocr_channel": message.channel,
                  "fixed_channel": channel}  # fmt: skip
        target = folder / f"{stem}.json"
        target.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        if picture is not None and picture.exists():
            shutil.copy(picture, folder / f"{stem}{picture.suffix}")
        return target

    def clean_up(self) -> None:
        """Day folders older than 14 days go, then the oldest samples until under the cap."""
        if not self._folder.exists():
            return
        oldest_kept = time.strftime(
            "%Y-%m-%d", time.localtime(self._clock() - self._keep_days * 86400)
        )
        days = sorted(p for p in self._folder.iterdir() if p.is_dir())
        for day in days:
            if day.name < oldest_kept:
                shutil.rmtree(day)
        samples = sorted(s for day in days if day.exists() for s in day.iterdir() if s.is_dir())
        sizes = {s: folder_size(s) for s in samples}
        total = sum(sizes.values())
        for sample in samples:  # names sort by date, then time
            if total <= self._cap_bytes:
                break
            shutil.rmtree(sample)
            total -= sizes[sample]
        for day in days:
            if day.exists() and not any(day.iterdir()):
                day.rmdir()

    def size_bytes(self) -> int:
        return folder_size(self._folder)

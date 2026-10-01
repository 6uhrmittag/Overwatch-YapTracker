"""Live chat into the database (#108): changed chat frames -> OCR -> parse -> channel -> who
(me / crew) -> dedup -> store, on a thread of its own so capture never waits for OCR.

If OCR falls behind, only the newest frame waits: chat on screen is still there a moment
later, and the dedup (#18) sorts out what was already stored.
"""

import logging
import threading
import time
from collections.abc import Callable

import numpy as np

from yaptracker import channels
from yaptracker.dedup import Dedup, Yap
from yaptracker.identity import Identity
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import ChatLine, parse

log = logging.getLogger(__name__)
LOAD_LOG_S = 60.0  # how often the reading cost goes to the log


def _fields(line: ChatLine) -> dict:
    return {
        "channel": line.channel,
        "speaker_raw": line.speaker,
        "hero": line.hero,
        "text": line.text,
        "ocr_confidence": line.confidence,
        "flagged": "overwatch" if line.flagged else None,
        "role": line.role,
    }


class ChatReader:
    def __init__(
        self,
        read: Callable[[np.ndarray], list[OcrLine]],
        store,
        matches,
        identity: Callable[[], Identity] = Identity,
        colours: Callable[[], dict[str, float]] = dict,
        paused: Callable[[], bool] = lambda: False,
        clock: Callable[[], float] = time.time,
        on_read: Callable[..., object] = lambda ts, image, ocr, lines, new: None,
    ) -> None:
        self._read, self._store, self._matches = read, store, matches
        self._identity, self._colours, self._paused, self._clock = (
            identity, colours, paused, clock
        )  # fmt: skip
        self._on_read = on_read  # debug samples of hard chat moments (#110)
        self._dedup = Dedup()
        self._stored: dict[int, int] = {}  # yap id -> chat_messages id
        self._pending: tuple[float, np.ndarray] | None = None
        self._wake = threading.Condition()
        self._stop = False
        self._thread: threading.Thread | None = None
        self.read_frames = 0
        self.busy_s = 0.0  # CPU time spent reading (OCR runs on this thread, #108)
        self._load_since, self._load_cpu = time.monotonic(), time.process_time()
        self._load_busy, self._load_frames = 0.0, 0

    def offer(self, image: np.ndarray) -> None:
        """From the capture thread: a chat frame with new text. Never blocks."""
        with self._wake:
            self._pending = (self._clock(), image)
            self._wake.notify()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="chat reader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._wake:
            self._stop = True
            self._wake.notify()
        if self._thread is not None:
            self._thread.join(timeout=10)  # an OCR call may be running; the store closes next

    def _run(self) -> None:
        while True:
            with self._wake:
                while self._pending is None and not self._stop:
                    self._wake.wait()
                if self._pending is None:  # stopping, and the last frame is done
                    return
                (ts, image), self._pending = self._pending, None
            try:
                self.read_frame(ts, image)
            except Exception:  # logged with traceback; the next frame is tried as usual
                log.exception("reading the chat failed")
                self._matches.chat_changed(ts)  # new text was there: the match still counts it

    def read_frame(self, ts: float, image: np.ndarray) -> list[Yap]:
        """One frame through the whole pipeline; returns the yaps it stored. (Tests call it.)"""
        if self._paused():  # paused after the frame was offered: nothing is read or kept
            return []
        started = time.thread_time()
        ocr = self._read(image)
        lines = self._identity().apply(channels.assign(parse(ocr), image, self._colours()))
        new, improved = self._dedup.update(ts, lines)
        if new:
            self._matches.chat_changed(ts)  # first: a new match may start with this yap
        for yap in new:
            self._stored[yap.id] = self._store.add_message(
                ts=ts, match_id=self._matches.match_id, **_fields(yap.best)
            )
        for yap in improved:
            if yap.id in self._stored:
                self._store.update_message(self._stored[yap.id], **_fields(yap.best))
        self._count(time.thread_time() - started)
        self._on_read(ts, image, ocr, lines, new)
        return new

    def _count(self, spent: float) -> None:
        self.read_frames += 1
        self.busy_s += spent
        self._load_busy += spent
        self._load_frames += 1
        now, cpu = time.monotonic(), time.process_time()
        if now - self._load_since >= LOAD_LOG_S:  # the "< 5 % of one core" goal, checkable
            wall = now - self._load_since
            log.info("chat reading: %d frames, %.0f ms CPU each; whole app: %.1f %% of a core",
                     self._load_frames, 1000 * self._load_busy / self._load_frames,
                     100 * (cpu - self._load_cpu) / wall)  # fmt: skip
            self._load_since, self._load_cpu = now, cpu
            self._load_busy, self._load_frames = 0.0, 0

"""Live chat into the database (#108): changed chat frames -> OCR -> parse -> channel -> who
(me / crew) -> dedup -> store, on a thread of its own so capture never waits for OCR.

If OCR falls behind, only the newest frame waits: chat on screen is still there a moment
later, and the dedup (#18) sorts out what was already stored.
"""

import logging
import math
import threading
import time
from collections.abc import Callable

import numpy as np

from yaptracker import channels, glyphs, priority
from yaptracker.dedup import Dedup, Yap
from yaptracker.identity import Identity
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import ChatLine, parse

log = logging.getLogger(__name__)
LOAD_LOG_S = 60.0  # how often the reading cost goes to the log
# At most one read per 1.5 s (#115): 9 of 10 reads find nothing new, and a line stays on screen
# for ~9 s, so it is still read several times. The newest frame waits, older ones are dropped.
MIN_GAP_S = 1.5


def _fields(line: ChatLine) -> dict:
    return {
        "channel": line.channel,
        "speaker_raw": line.speaker,
        "hero": line.hero,
        "text": line.text,
        "ocr_confidence": line.confidence,
        "flagged": "overwatch" if line.flagged else None,
        "role": line.role,
        "has_glyphs": glyphs.has_glyphs(line.text),
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
        min_gap_s: float = MIN_GAP_S,
        pictures=None,
        players=None,
        on_player: Callable[[int | None, int | None], object] = lambda player, match: None,
    ) -> None:
        self._read, self._store, self._matches = read, store, matches
        self._identity, self._colours, self._paused, self._clock = (
            identity, colours, paused, clock
        )  # fmt: skip
        self._on_read = on_read  # debug samples of hard chat moments (#110)
        self._pictures = pictures  # the picture of every stored line (#120)
        self._players = players  # who said it (#23)
        self._on_player = on_player  # a familiar face may be back (#26)
        self._speakers: dict[int, tuple[str | None, int | None]] = {}  # yap id -> (speaker, player)
        self._seen_colours: dict[str, float] = {}  # channel colours learned while reading (#173)
        self.min_gap_s = min_gap_s  # Settings can change it while running (#152)
        self._last_read = -math.inf  # monotonic time of the last read's start
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
        priority.lower_this_thread()  # OCR waits for the game, not the other way round (#187)
        while True:
            with self._wake:
                while self._pending is None and not self._stop:
                    self._wake.wait()
                if self._pending is None:  # stopping, and the last frame is done
                    return
                # Too soon after the last read: wait, newer frames replace the pending one.
                wait = self._last_read + self.min_gap_s - time.monotonic()
                if wait > 0 and not self._stop:
                    self._wake.wait(wait)
                    continue
                (ts, image), self._pending = self._pending, None
            self._last_read = time.monotonic()
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
        ocr = glyphs.mark(image, self._read(image))  # icons OCR can't spell become ◇ (#128)
        parsed = parse(ocr)
        self._seen_colours.update(channels.learn(parsed, image))  # e.g. HDR shifts them (#173)
        known = {**self._colours(), **self._seen_colours}
        lines = self._identity().apply(channels.assign(parsed, image, known))
        new, improved = self._dedup.update(ts, lines)
        if new:
            self._matches.chat_changed(ts)  # first: a new match may start with this yap
        for yap in new:
            player = self._player(yap, ts)
            self._stored[yap.id] = self._store.add_message(
                ts=ts, match_id=self._matches.match_id, player_id=player, **_fields(yap.best)
            )
            self._keep_picture(yap, image)
            if yap.best.channel != "system":  # "[x] started playing" is a friend online, not here
                self._on_player(player, self._matches.match_id)
        for yap in improved:
            if yap.id in self._stored:
                self._store.update_message(
                    self._stored[yap.id], player_id=self._player(yap, ts), **_fields(yap.best)
                )
                if yap.best is yap.last:  # read better in this very frame: its picture, too
                    self._keep_picture(yap, image)
        self._count(time.thread_time() - started)
        self._on_read(ts, image, ocr, lines, new)
        return new

    def _player(self, yap: Yap, ts: float) -> int | None:
        """The player for the yap's best reading; linked again only when the speaker changed."""
        speaker = yap.best.speaker
        known = self._speakers.get(yap.id)
        if known is not None and known[0] == speaker:
            return known[1]
        pid = self._players.link(speaker, ts, yap.best.confidence) if self._players else None
        self._speakers[yap.id] = (speaker, pid)
        return pid

    def _keep_picture(self, yap: Yap, image: np.ndarray) -> None:
        if self._pictures is not None:
            self._pictures.save(self._stored[yap.id], yap.first_seen, image, yap.last.box)

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

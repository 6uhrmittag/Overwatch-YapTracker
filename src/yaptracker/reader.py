"""Live chat into the database (#108): changed chat frames -> OCR -> parse -> channel -> who
(me / crew) -> dedup -> store, on a thread of its own so capture never waits for OCR.

If OCR falls behind, only the newest frame waits: chat on screen is still there a moment
later, and the dedup (#18) sorts out what was already stored.

During a match read afterwards (#335), frames wait in `later` instead, and are read once the
game is idle, oldest first, into the match they were seen in. While any wait, new frames queue
behind them: everything is read in the order it was seen, so the dedup sees one stream.
"""

import logging
import math
import threading
import time
from collections.abc import Callable

import numpy as np

from yaptracker import channels, glyphs, priority
from yaptracker.cpu_parts import CPU
from yaptracker.dedup import FADE_S, YAP_KINDS, Dedup, Yap, match_key
from yaptracker.identity import Identity
from yaptracker.input_row import without_input
from yaptracker.later import Kept, LaterFrames
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import ChatLine, parse
from yaptracker.reading_mode import AFTER

log = logging.getLogger(__name__)
LOAD_LOG_S = 60.0  # how often the reading cost goes to the log
# At most one read per 1.5 s (#115): 9 of 10 reads find nothing new, and a line stays on screen
# for ~9 s, so it is still read several times. The newest frame waits, older ones are dropped.
MIN_GAP_S = 1.5
CPU_GOAL = 15.0  # % of one core for the whole app over a minute (Definition of done)
BUSY_GAP_S = 3.0  # read at most this often for the next minute when the last one was above it
REREADS = 3  # extra reads for a line still on screen without a good reading (#195)
LATER_POLL_S = 2.0  # frames wait for later: how often to look whether the game is idle yet


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
        on_player: Callable[[int | None, int | None, bool], object] = lambda *heard: None,
        save_colours: Callable[[dict[str, float]], object] = lambda colours: None,
        modes: Callable[[], str] = lambda: "",
        later: LaterFrames | None = None,
        read_kept: Callable[[np.ndarray, str], list[OcrLine]] | None = None,
        deferring: Callable[[], bool] = lambda: False,
        idle: Callable[[], bool] = lambda: True,
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
        self._read_match: int | None = None  # the match of the last read
        self._on_screen: set[str] = set()  # match keys of the lines in the last read (#179)
        self._reread_until, self._rereads_left = -math.inf, 0  # read weak lines again (#195)
        self._weak: set[int] = set()  # yaps that already got their re-reads
        self._save_colours = save_colours  # the group colour is rare: kept for next time (#80)
        self._modes = modes  # which reading mode read the frames, for the log line (#331)
        # Frames read after the match (#335): kept while deferring, read when idle (fast) or
        # in a live match (at the live pace), each with the mode it was seen with.
        self.later = later or LaterFrames(lambda: self.min_gap_s, None)
        self._read_kept = read_kept or (lambda image, mode: read(image))
        self._deferring, self._idle = deferring, idle
        self._batch: tuple[float, int] | None = None  # (started, frames) of reading kept ones
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
        self.busy = False  # the last minute was above the CPU goal: read less often (#249)

    def offer(self, image: np.ndarray, mode: str | None = None) -> None:
        """From the capture thread: a chat frame with new text. Never blocks. mode: how it's
        read if it has to wait ('after': the match is read afterwards, #335)."""
        ts = self._clock()
        with self._wake:  # wakes the reader either way: kept frames are looked at every 2 s
            if mode == AFTER or len(self.later):
                self.later.add(ts, image, self._matches.match_id, mode)
            else:
                self._pending = (ts, image)
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
        lost = self.later.discard()  # quitting mid-match: those frames are never read
        if lost is not None:
            log.warning("quitting with chat frames unread: %s", _span(*lost))
            self._store.close_gap(self._store.open_gap(lost[0], "deferred_lost"), lost[1])

    def _run(self) -> None:
        priority.lower_this_thread()  # OCR waits for the game, not the other way round (#187)
        while True:
            with self._wake:
                while self._pending is None and not self._stop and not self._kept_due():
                    self._wake.wait(LATER_POLL_S if len(self.later) else None)
                if self._pending is None and self._stop:  # stopping, and the last frame is done
                    return
                # Too soon after the last read: wait, newer frames replace the pending one.
                # Kept frames go one after the other while the game is idle (#335).
                gap = max(self.min_gap_s, BUSY_GAP_S) if self.busy else self.min_gap_s
                fast = self._pending is None and self._idle()
                wait = 0 if fast else self._last_read + gap - time.monotonic()
                if wait > 0 and not self._stop:
                    self._wake.wait(wait)
                    continue
                kept = self.later.pop() if self._pending is None else None
                if self._pending is not None:
                    (ts, image), self._pending = self._pending, None
                elif kept is None:
                    continue
                else:
                    ts, image = kept.ts, kept.image
            self._last_read = time.monotonic()
            try:
                self.read_frame(ts, image, kept)
            except Exception:  # logged with traceback; the next frame is tried as usual
                log.exception("reading the chat failed")
                self._matches.chat_changed(ts)  # new text was there: the match still counts it
            if kept is not None:
                self._kept_read(kept)

    def _kept_due(self) -> bool:
        """Frames wait, and the match they wait for is over (or the game is gone)."""
        return len(self.later) > 0 and not self._deferring()

    def _kept_read(self, kept: Kept) -> None:
        """Says in the log when reading the kept frames starts and how it went (#335)."""
        started, frames = self._batch or (time.monotonic(), 0)
        if self._batch is None:
            log.info("reading %d chat frames kept since %s", len(self.later) + 1,
                     time.strftime("%H:%M:%S", time.localtime(kept.ts)))  # fmt: skip
        self._batch = (started, frames + 1)
        if not len(self.later):
            log.info("read %d kept chat frames in %.0f s", frames + 1, time.monotonic() - started)
            self._batch = None

    def read_frame(self, ts: float, image: np.ndarray, kept: Kept | None = None) -> list[Yap]:
        """One frame through the whole pipeline; returns the yaps it stored. (Tests call it.)
        kept: a frame that waited (#335), read with its own mode into its own match."""
        if kept is None and self._paused():  # paused after the frame was offered: not kept
            return []
        started = time.thread_time()
        known = {**self._colours(), **self._seen_colours}
        ocr_lines = self._read(image) if kept is None else self._read_kept(image, kept.mode)
        read = without_input(ocr_lines, image)  # what you type isn't said yet (#254)
        read = channels.cut_glued(read, image, known)  # "gg 512" -> "gg" (#172)
        ocr = glyphs.mark(image, read)  # icons OCR can't spell become ◇ (#128)
        parsed = parse(ocr)
        learned = channels.learn(parsed, image)
        self._seen_colours.update(learned)  # e.g. HDR shifts them (#173)
        saved = self._colours()
        if "group" in learned and (
            "group" not in saved or channels.hue_distance(learned["group"], saved["group"]) > 10
        ):
            self._save_colours({"group": learned["group"]})  # seen only when someone uses it
        known = {**saved, **self._seen_colours}
        lines = self._identity().apply(channels.assign(parsed, image, known))
        new, improved = self._dedup.update(ts, lines)
        before = self._matches.match_id
        if new:
            self._matches.chat_changed(ts)  # first: a new match may start with this yap
        # The first read of a match that began without this chat can still show lines of the
        # match before (#179): those that were on screen in the read before it belong there.
        current, previous = self._matches.match_id, self._matches.previous_match_id
        if kept is not None and current == before:  # into the match it was seen in (#335)
            before = current = kept.match_id
            previous = self._read_match
        old = set()
        if current == before and current != self._read_match and previous is not None:
            old = {yap.id for yap in new if match_key(yap.best) in self._on_screen}
            if old:
                log.info("%d line(s) still on screen from match %d", len(old), previous)
        self._read_match = current
        self._on_screen = {match_key(line) for line in lines if line.kind in YAP_KINDS}
        self._want_reread(ts, lines)
        for yap in new:
            player = self._player(yap, ts)
            match_id = previous if yap.id in old else current
            self._stored[yap.id] = self._store.add_message(
                ts=ts, match_id=match_id, player_id=player, **_fields(yap.best)
            )
            self._keep_picture(yap, image)
            if yap.best.channel != "system":  # "[x] started playing" is a friend online, not here
                self._on_player(player, match_id, kept is not None and kept.mode == AFTER)
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

    def wants_reread(self) -> bool:
        """A line on screen has no good reading yet: offer frames even without new text."""
        return self._rereads_left > 0 and self._clock() < self._reread_until

    def _want_reread(self, ts: float, lines: list) -> None:
        """Called after each read. A weak line seen in it gets REREADS more reads while it can
        still be on screen; reads in that time use them up, a good reading ends them."""
        seen = {id(line) for line in lines}
        weak = [yap for yap in self._dedup.recent if id(yap.last) in seen and yap.weak]
        self._weak &= {yap.id for yap in self._dedup.recent}
        if not weak:
            self._rereads_left = 0
            return
        if ts < self._reread_until:
            self._rereads_left -= 1
        for yap in weak:
            if yap.id not in self._weak:
                self._weak.add(yap.id)
                self._reread_until = max(self._reread_until, yap.first_seen + FADE_S)
                self._rereads_left = REREADS

    def _player(self, yap: Yap, ts: float) -> int | None:
        """The player for the yap's best reading; linked again only when the speaker changed.
        Nobody for a system line: "[x] stopped playing" is the friend list, not meeting x (#306).
        """
        speaker = yap.best.speaker if yap.best.channel != "system" else None
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
        CPU.add("reading", spent)  # the per-part line (#302)
        self.read_frames += 1
        self.busy_s += spent
        self._load_busy += spent
        self._load_frames += 1
        now, cpu = time.monotonic(), time.process_time()
        if now - self._load_since >= LOAD_LOG_S:  # the "< 5 % of one core" goal, checkable
            wall = now - self._load_since
            whole = 100 * (cpu - self._load_cpu) / wall
            # Above the goal: read every 3 s for a minute (chat stays ~9 s on screen, #249).
            self.busy = whole > CPU_GOAL
            modes = self._modes()
            log.info("chat reading: %d frames, %.0f ms CPU each%s; whole app: %.1f %% of a core%s",
                     self._load_frames, 1000 * self._load_busy / self._load_frames,
                     f" ({modes})" if modes else "", whole,
                     "; reading every 3 s for a minute" if self.busy else "")  # fmt: skip
            self._load_since, self._load_cpu = now, cpu
            self._load_busy, self._load_frames = 0.0, 0


def _span(first: float, last: float) -> str:
    clock = time.strftime("%H:%M:%S", time.localtime(first))
    return f"{clock} to {time.strftime('%H:%M:%S', time.localtime(last))}"

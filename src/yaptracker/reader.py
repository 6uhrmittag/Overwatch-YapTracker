"""Live chat into the database (#108): changed chat frames -> OCR -> parse -> channel -> who
(me / crew) -> dedup -> store, on a thread of its own so capture never waits for OCR.

If OCR falls behind, only the newest frame waits: chat on screen is still there a moment
later, and the dedup (#18) sorts out what was already stored.

During a match read afterwards (#335), frames wait in `later` instead, and are read once the
game is idle, oldest first, into the match they were seen in. While any wait between matches, new
frames queue behind them: everything is read in the order it was seen, so the dedup sees one
stream. Once a live match runs, its frames go first and the kept ones only fill the gaps (#597);
from then on the two are two streams, each with its own dedup, until the kept ones are read.
"""

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import replace

import numpy as np

from yaptracker import channels, cpu_parts, glyphs, icons, priority, side_work, top_row
from yaptracker.cpu_parts import CPU
from yaptracker.dedup import (
    FADE_S,
    YAP_KINDS,
    Dedup,
    Yap,
    hero_speaker,
    match_key,
    stored_as,
    text_key,
)
from yaptracker.identity import Identity
from yaptracker.input_row import without_input
from yaptracker.later import PER_PICTURE_S, Backlog, Kept, LaterFrames
from yaptracker.lines import row
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import ChatLine, parse
from yaptracker.reading_mode import AFTER, BEST
from yaptracker.tidy import TidyMatch, differs

log = logging.getLogger(__name__)
LOAD_LOG_S = 60.0  # how often the reading cost goes to the log
# At most one read per 1.5 s (#115): 9 of 10 reads find nothing new, and a line stays on screen
# for ~9 s, so it is still read several times. The newest frame waits, older ones are dropped.
MIN_GAP_S = 1.5
CPU_GOAL = 15.0  # % of one core for the whole app over a minute (Definition of done)
BUSY_GAP_S = 3.0  # read at most this often for the next minute when the last one was above it
REREADS = 3  # extra reads for a line still on screen without a good reading (#195)
LATER_POLL_S = 2.0  # frames wait for later: how often to look whether the game is idle yet
# Between matches the box reaches into the menu (#176), whose art moves and has big text: every
# frame "changed" and was read every 3 s for an hour with no chat in it (#115, 2026-10-06 log).
# After this many reads without a chat line, read every MENU_GAP_S until one shows up. A line
# stays ~9 s, so it's still read at least once.
NO_CHAT_READS = 3
MENU_GAP_S = 6.0
FAIL_LIMIT = 5  # reads failing in a row before a crash gap opens and Live says so (#457)
RATE_GAP_S = 30.0  # kept frames read further apart than this: a pause, not the reading pace
RATE_WEIGHT = 0.2  # how much each kept frame moves the time-left guess (#501)
UNSTORED_LOOK_S = 600.0  # seen-but-not-stored: compared with the lines stored this long (#504)
# ...and with the last lines stored before that, this evening: an opened chat shows old lines as
# long as nothing newer came, and a stream that just started knows none of them (#602).
STORED_FAR_S, STORED_ROWS = 4 * 3600.0, 40
OLDER = "older than every line I know"  # the opened chat's history from before I read (#179)


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


def _marked(yap: Yap) -> bool:
    return glyphs.GLYPH in yap.best.text


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
        on_read: Callable[..., object] = lambda ts, image, ocr, lines, new, unstored: None,
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
        gated: Callable[[], bool] = lambda: True,
        keep_gap_s: Callable[[], float] | None = None,
        starved: Callable[[], bool] = lambda: False,
        lowest: bool = True,
    ) -> None:
        self._read, self._store, self._matches = read, store, matches
        self._identity, self._colours, self._paused, self._clock = (
            identity, colours, paused, clock
        )  # fmt: skip
        self._on_read = on_read  # debug samples of hard chat moments (#110)
        self._pictures = pictures  # the picture of every stored line (#120)
        self._players = players  # who said it (#23)
        self._players_seen = 0  # the matcher's generation _speakers is from (#458)
        self._on_player = on_player  # a familiar face may be back (#26)
        self._speakers: dict[int, tuple[str | None, int | None]] = {}  # yap id -> (speaker, player)
        self._seen_colours: dict[str, float] = {}  # channel colours learned while reading (#173)
        self._read_match: int | None = None  # the match of the last read
        self._on_screen: set[str] = set()  # match keys of the lines in the last read (#179)
        self._unstored_said: dict[int | None, list[str]] = {}  # reported, per match (#504)
        # (key, words of text) of the stored lines the last report was compared with, and the
        # reported keys that are like one stored more than UNSTORED_LOOK_S ago (#602)
        self._near: list[tuple[str, int]] = []
        self._far_like: set[str] = set()
        self._reread_until, self._rereads_left = -math.inf, 0  # read weak lines again (#195)
        self._weak: set[int] = set()  # yaps that already got their re-reads
        self._save_colours = save_colours  # the group colour is rare: kept for next time (#80)
        self._modes = modes  # which reading mode read the frames, for the log line (#331)
        # Frames read after the match (#335): kept while deferring, read when idle (fast) or
        # in a live match (at the live pace), each with the mode it was seen with.
        # "is not None": an empty buffer is falsy (it has a length), and the app passes one empty
        # One frame per this is kept to read later (#335, #336); the app keeps it at 1.5 s even
        # "as fast as it can" (#588): kept frames would pile up at the capture's 2 a second.
        self._keep_gap = keep_gap_s or (lambda: self.min_gap_s)
        self.later = later if later is not None else LaterFrames(self._keep_gap, None)
        self._read_kept = read_kept or (lambda image, mode: read(image))
        self._deferring, self._idle = deferring, idle
        # The busy gate (#249) is for the default choices; a match read live with best is the
        # user's trade of CPU for quality, and keeps its chosen gap (#588).
        self._gated = gated
        # The app waits for a core (late watchdog ticks, #601): every choice reads less often,
        # best live and "as fast as it can" too. More reads then mean more waiting, not more chat.
        self._starved, self._held_back = starved, False
        # Its thread at the lowest priority while it does the OCR itself (#187). With the OCR in
        # its own process (#563) it only parses and stores: milliseconds, and a thread put to
        # sleep at the lowest priority while it holds Python's lock stalls the whole process.
        self._lowest = lowest
        self._batch: tuple[float, int] | None = None  # (started, frames) of reading kept ones
        # Time between two kept frames read through, as the UI's time left (#501): in a live
        # match they only go between live reads, so this beats the OCR time alone.
        self.per_picture_s, self._paced = PER_PICTURE_S, False
        self._kept_at: float | None = None
        # Light matches (#336): their changed frames, read again with the best quality when idle
        self.tidy_frames = LaterFrames(self._keep_gap, None)
        self._tidy: TidyMatch | None = None
        self._tidy_paused = False  # said once in the log (#432)
        self.tidied: tuple[int, int, int] | None = None  # (match, fixed, found) of the last one
        self.min_gap_s = min_gap_s  # Settings can change it while running (#152)
        self._last_read = -math.inf  # monotonic time of the last read's start
        self._dedup = Dedup()
        # Kept frames read side by side with live ones (#597): their own dedup and screen
        # (read match, keys on screen), so neither stream takes the other's lines for its own.
        self._kept_dedup: Dedup | None = None
        self._kept_screen: tuple[int | None, set[str]] = (None, set())
        self._live_first = False  # a live match ran since the last match read afterwards
        self._last_live = -math.inf  # monotonic time of the last live read's start
        self._kept_cost = PER_PICTURE_S  # how long one kept read takes, about (#597)
        self._stored: dict[int, int] = {}  # yap id -> chat_messages id
        self._pending: tuple[float, np.ndarray] | None = None
        self._wake = threading.Condition()
        self._stop = False
        self._thread: threading.Thread | None = None
        self.read_frames = 0
        self.busy_s = 0.0  # CPU time spent reading (this thread's and the OCR child's, #563)
        self._load_since, self._load_cpu = time.monotonic(), cpu_parts.app_cpu()
        self._load_busy, self._load_frames = 0.0, 0
        self._offered = 0  # frames with new text since the last log line (#350)
        self.busy = False  # the last minute was above the CPU goal: read less often (#249)
        self._no_chat = 0  # reads in a row without a chat line (#115)
        self.failing = 0  # reads in a row that failed (#457); Live says so from FAIL_LIMIT on
        self._failing_since = 0.0
        self._failing_gap: int | None = None

    def gap_s(self) -> float:
        """Seconds between two live reads: the chosen one; 3 s for a minute after one above the
        CPU goal, unless the match is read live with best (#249, #588); 3 s for a minute after
        the app was starved, whatever was chosen (#601)."""
        if self._starved():
            self._held_back = True
            return max(self.min_gap_s, BUSY_GAP_S)
        return max(self.min_gap_s, BUSY_GAP_S) if self.busy and self._gated() else self.min_gap_s

    def _kept_gap_s(self) -> float:
        gap = self._keep_gap()
        if self._starved():
            self._held_back = True
            return max(gap, BUSY_GAP_S)
        return max(gap, BUSY_GAP_S) if self.busy else gap

    def _gap_words(self) -> str:
        """For the log line (#588): which gap the reads used and why."""
        chosen = "as fast as it can" if not self.min_gap_s else f"every {self.min_gap_s:g} s"
        if self._held_back:  # some time in the minute this line is about (#601)
            return (
                f"reading every {max(self.min_gap_s, BUSY_GAP_S):g} s for a minute (the app"
                f" was starved: late watchdog ticks; chosen {chosen})"
            )
        if not self.busy or self.gap_s() == self.min_gap_s and self._gated():
            return f"reading {chosen} (chosen)"
        if not self._gated():
            return f"reading {chosen} (chosen; above the CPU goal, but best live isn't held back)"
        gap = self.gap_s()
        return f"reading every {gap:g} s for a minute (above the CPU goal; chosen {chosen})"

    def offer(self, image: np.ndarray, mode: str | None = None) -> None:
        """From the capture thread: a chat frame with new text. Never blocks. mode: how it's
        read if it has to wait ('after': the match is read afterwards, #335)."""
        ts = self._clock()
        if mode == AFTER:  # not read now, but the match knows chat is going on (#307, #345)
            self._matches.chat_activity(ts)
        with self._wake:  # wakes the reader either way: kept frames are looked at every 2 s
            self._offered += 1  # for the menu's log line (#350)
            if mode == AFTER:
                self._live_first = False
            elif not self._idle():  # a live match runs: before any backlog (#597)
                self._live_first = True
            if mode == AFTER or (len(self.later) and not self._live_first):
                self.later.add(ts, image, self._matches.match_id, mode)
            else:
                self._pending = (ts, image)
            self._wake.notify()

    def keep_for_tidy(self, image: np.ndarray) -> None:
        """From the capture thread: a changed frame of a light match, read again later (#336)."""
        self.tidy_frames.add(self._clock(), image, self._matches.match_id, BEST)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="chat reader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._wake:
            self._stop = True
            self._wake.notify()
        if self._thread is not None:
            self._thread.join(timeout=10)  # an OCR call may be running; the store closes next
        if self.tidy_frames.discard() is not None:  # its light lines stay as they are
            log.info("quitting before the last light match was tidied up")
        lost = self.later.close()  # unread frames to disk for the next start (#349)
        if lost is not None:
            log.warning("quitting with chat frames unread: %s", _span(*lost))
            self._store.close_gap(self._store.open_gap(lost[0], "deferred_lost"), lost[1])

    def _run(self) -> None:
        """The reader thread never ends but on stop (#457): whatever trips a turn is logged
        (once a minute) and the loop goes on, its waiting frames intact."""
        if self._lowest:
            priority.lower_this_thread()  # OCR waits for the game, not the other way round (#187)
        while True:
            try:
                return self._loop()
            except Exception as error:
                side_work.failed("the chat reader", error, then="it goes on")
                time.sleep(1.0)  # never a hot loop

    def _loop(self) -> None:
        while True:
            self._note_tidy_paused()
            with self._wake:
                while (self._pending is None and not self._stop and not self._kept_due()
                       and not self._tidy_due()):  # fmt: skip
                    waiting = len(self.later) or len(self.tidy_frames)
                    self._wake.wait(LATER_POLL_S if waiting else None)
                if self._pending is None and self._stop:  # stopping, and the last frame is done
                    return
                what, wait = self._next(time.monotonic())
                if what is None:
                    self._wake.wait(wait)
                    continue
                kept = tidy = None
                if what == "live":
                    (ts, image), self._pending = self._pending, None
                elif what == "kept":
                    kept = self.later.pop()
                    if kept is None:
                        continue
                    ts, image = kept.ts, kept.image
                elif (tidy := self.tidy_frames.pop()) is None:
                    continue
            if tidy is not None:  # lowest priority: only when nothing else waits (#336)
                try:
                    self.tidy_frame(tidy)
                except Exception:
                    log.exception("tidying up the chat failed")
                continue
            self._last_read = time.monotonic()
            if kept is None:
                self._last_live = self._last_read
            live = kept is None  # kept frames carry old times: only live reads count (#457)
            paused = live and self._paused()  # read_frame skips it: not a good read either
            ok = False
            try:
                self.read_frame(ts, image, kept)
                ok = True
            except Exception as error:  # logged with traceback; the next frame is tried as usual
                side_work.failed("reading the chat", error, then="the next frame is read")
                self._failed_read(ts, live)
            else:
                if live and not paused:
                    self._read_ok(ts)
            if kept is not None:
                if ok:  # a failed read says nothing about how long one takes
                    cost = time.monotonic() - self._last_read
                    self._kept_cost += RATE_WEIGHT * (cost - self._kept_cost)
                self._kept_read(kept)

    def _next(self, now: float) -> tuple[str | None, float]:
        """What to read now: ('live' | 'kept' | 'tidy', 0), or (None, seconds to wait).
        Live frames go first and keep their own gap (#597). Kept ones go one after the other
        while the game is idle, in a live match one per kept gap after any read, always gated
        (#588); either way only if they're done before the waiting live frame is due. Tidy
        frames only when nothing else waits (#336)."""
        live_wait = math.inf
        if self._pending is not None:
            gap = self.gap_s()
            if self.menu:
                gap = max(gap, MENU_GAP_S)
            live_wait = 0.0 if self._stop else self._last_live + gap - now
            if live_wait <= 0:
                return "live", 0.0
        if self._kept_due():
            kept_wait = 0.0 if self._idle() else self._last_read + self._kept_gap_s() - now
            if kept_wait <= 0 and live_wait >= self._kept_cost:
                return "kept", 0.0
            return None, min(live_wait, max(kept_wait, 0.0) or live_wait)
        if self._pending is None and self._tidy_due():
            return "tidy", 0.0
        return None, (live_wait if self._pending is not None else LATER_POLL_S)

    def _failed_read(self, ts: float, live: bool = True) -> None:
        """Live reads failing in a row (#457): from FAIL_LIMIT on a crash gap is open (from the
        first of them) and Live says so."""
        try:
            self._matches.chat_changed(ts)  # new text was there: the match still counts it
        except Exception as error:  # the store itself may be what fails
            side_work.failed("recording a failed read", error, then="it goes on")
        if not live:
            return
        self.failing += 1
        if self.failing == 1:
            self._failing_since = ts
        if self.failing >= FAIL_LIMIT and self._failing_gap is None:
            try:  # tried again with every failure until the store takes it
                self._failing_gap = self._store.open_gap(self._failing_since, "crash")
            except Exception as error:
                side_work.failed("opening the gap of failed reads", error, then="it goes on")

    def _read_ok(self, ts: float) -> None:
        if self._failing_gap is not None:
            try:
                self._store.close_gap(self._failing_gap, ts)
                self._failing_gap = None
            except Exception as error:
                side_work.failed("closing the gap of failed reads", error, then="it goes on")
        self.failing = 0

    def _tidy_due(self) -> bool:
        """Frames of a light match wait, and the game is idle (the next match pauses it)."""
        return len(self.tidy_frames) > 0 and not len(self.later) and self._idle()

    def _kept_due(self) -> bool:
        """Frames wait, and the match they wait for is over (or the game is gone)."""
        return len(self.later) > 0 and not self._deferring()

    def backlog(self) -> Backlog:
        """What waits to be read after its match, for the UI (#501)."""
        waiting, restored = self.later.waiting()
        return Backlog(waiting, self.per_picture_s, self._deferring(), self._matches.match_id,
                       restored)  # fmt: skip

    def _kept_read(self, kept: Kept) -> None:
        """Says in the log when reading the kept frames starts and how it went (#335)."""
        self.later.finish()
        now = time.monotonic()
        if self._kept_at is not None and now - self._kept_at < RATE_GAP_S:
            weight = RATE_WEIGHT if self._paced else 1.0  # the first one replaces the guess
            self.per_picture_s += weight * (now - self._kept_at - self.per_picture_s)
            self._paced = True
        self._kept_at = now
        started, frames = self._batch or (time.monotonic(), 0)
        if self._batch is None:
            log.info("reading %d chat frames kept since %s", len(self.later) + 1,
                     time.strftime("%H:%M:%S", time.localtime(kept.ts)))  # fmt: skip
        self._batch = (started, frames + 1)
        if not len(self.later):
            with self._wake:
                self._one_stream()
            _, dropped = self.later.take_counts()
            drops = ", ".join(f"match {m}: {n}" for m, n in sorted(dropped.items(), key=str))
            log.info("read %d kept chat frames in %.0f s%s", frames + 1, time.monotonic() - started,
                     f" (dropped for the memory cap: {drops})" if drops else "")  # fmt: skip
            self._batch = None

    def _one_stream(self) -> None:
        """The kept frames are read through (#597): if the newest frames went to them, their
        dedup goes on as the live one; otherwise theirs goes."""
        if self._kept_dedup is not None and not self._live_first:
            self._dedup = self._kept_dedup
            self._read_match, self._on_screen = self._kept_screen
            self._weak, self._rereads_left = set(), 0  # those were the other dedup's yaps
        self._kept_dedup, self._kept_screen = None, (None, set())

    def read_frame(self, ts: float, image: np.ndarray, kept: Kept | None = None) -> list[Yap]:
        """One frame through the whole pipeline; returns the yaps it stored. (Tests call it.)
        kept: a frame that waited (#335), read with its own mode into its own match."""
        if kept is None and self._paused():  # paused after the frame was offered: not kept
            return []
        if kept is None and self._live_first and len(self.later) and self._kept_dedup is None:
            # a live frame before kept ones (#597): they keep what was read so far, live
            # starts its own
            self._kept_dedup, self._kept_screen = self._dedup, (self._read_match, self._on_screen)
            self._dedup = Dedup(ids=self._kept_dedup.ids)
        side = kept is not None and self._kept_dedup is not None  # the kept stream of two
        dedup = self._kept_dedup if side else self._dedup
        started = _cpu_now()
        ocr_lines = self._read(image) if kept is None else self._read_kept(image, kept.mode)
        ocr, lines = self._lines(image, ocr_lines, dedup.recent)
        new, improved = dedup.update(ts, lines)
        before = self._matches.match_id
        # first: a new match may start with this yap. Not for frames read after their match:
        # they belong to it, also after a restart when no match is open yet (#349). Not for a
        # system line: "2 friends playing Overwatch." in the menu started a match that never
        # ended (#417); friend notices and endorsements aren't match chat.
        said = any(yap.best.kind != "system" for yap in new)
        # nor for a kept frame of a match gone by: its old time would be the running one's (#597)
        if said and (kept is None or kept.mode != AFTER and kept.match_id == before):
            self._matches.chat_changed(ts)
        # The first read of a match that began without this chat can still show lines of the
        # match before (#179): those that were on screen in the read before it belong there.
        current, previous = self._matches.match_id, self._matches.previous_match_id
        read_match, on_screen = self._kept_screen if side else (self._read_match, self._on_screen)
        if kept is not None and current == before:  # into the match it was seen in (#335)
            before = current = kept.match_id
            previous = read_match
        old = set()
        if current == before and current != read_match and previous is not None:
            old = {yap.id for yap in new if match_key(yap.best) in on_screen}
            if old:
                log.info("%d line(s) still on screen from match %d", len(old), previous)
        screen = (current, {match_key(line) for line in lines if line.kind in YAP_KINDS})
        if side:
            self._kept_screen = screen
        else:
            self._read_match, self._on_screen = screen
            self._want_reread(ts, lines)
            self._no_chat = 0 if any(ln.kind in YAP_KINDS for ln in lines) else self._no_chat + 1
        seen_twice = self._really_unstored(ts, dedup.unstored, current)
        adopted, refused, completed = self._adopt(seen_twice, dedup, current)
        improved = improved + [yap for yap in completed if yap not in improved]
        for yap in new + [yap for yap, _ in adopted]:
            player = self._player(yap, ts)
            match_id = previous if yap.id in old else current
            if yap.id in (into := {a.id: m for a, m in adopted}):  # seen twice (#602)
                match_id = into[yap.id]
            elif yap.after in self._stored:  # missed earlier, read between two lines (#423)
                above = self._store.message(self._stored[yap.after])
                match_id = above.match_id if above is not None else match_id
            self._stored[yap.id] = self._store.add_message(
                ts=yap.first_seen, match_id=match_id, player_id=player, **self._named(yap, image)
            )
            self._keep_picture(yap, image)
            if yap.best.channel != "system":  # "[x] started playing" is a friend online, not here
                self._on_player(player, match_id, kept is not None and kept.mode == AFTER)
        for yap in improved:
            if yap.id in self._stored:
                stored = self._store.message(self._stored[yap.id]) if _marked(yap) else None
                self._store.update_message(
                    self._stored[yap.id], player_id=self._player(yap, ts),
                    **self._named(yap, image, stored))  # fmt: skip
                if yap.best is yap.last:  # read better in this very frame: its picture, too
                    self._keep_picture(yap, image)
        self._count(_cpu_now() - started)
        if adopted:  # a missed line as a number, not a feeling (#425); now kept (#602)
            log.info("chat reading: %d line(s) seen twice, stored now: %s", len(adopted),
                     "; ".join(_said(yap.best) for yap, _ in adopted))  # fmt: skip
        if refused:
            log.info("chat reading: %d line(s) seen twice but never stored: %s", len(refused),
                     "; ".join(f"{_said(line)} ({why})" for line, why in refused))  # fmt: skip
        try:
            self._on_read(ts, image, ocr, lines, new + [yap for yap, _ in adopted],
                          [line for line, _ in refused])  # fmt: skip
        except Exception as error:  # debug samples never fail a read (#452)
            side_work.failed("saving a debug sample", error)
        return new + [yap for yap, _ in adopted]

    def _adopt(
        self, rows: list[ChatLine], dedup: Dedup, match: int | None
    ) -> tuple[list[tuple[Yap, int | None]], list[tuple[ChatLine, str]], list[Yap]]:
        """Rows seen twice and stored nowhere become lines (#602): ([(line, its match)], [(row,
        why not)], [stored lines a row completed, #609]). Dedup only stored new rows below the
        last known line and missed ones between two neighbours (#423); a row above the known
        lines of an opened chat (Marv re-opened it to get a lost line back) was real, read well
        twice, and dropped. Its match: the one of the known line right below it (it was said
        before that one), else the read's."""
        adopted, refused, completed = [], [], []
        for line in rows:
            # the whole of a line stored cut: that line gets its text, no second one (#609)
            if match_key(line) not in self._far_like:  # before "read wrong": it begins it
                whole = dedup.whole_of(line)
                if whole is not None and whole.id in self._stored:
                    dedup.complete(line, whole)
                    completed.append(whole)
                    continue
                if whole is not None:
                    refused.append((line, "a piece of a line that isn't stored"))
                    continue
            why = self._why_not(line, dedup)
            got = None if why else dedup.adopt(line)
            if got is None:
                refused.append((line, why or OLDER))
                continue
            yap, below = got
            under = (
                self._store.message(self._stored[below.id]) if below.id in self._stored else None
            )
            # also "no match": said in the menu before a line stored there (as #423 does)
            adopted.append((yap, under.match_id if under is not None else match))
        if completed:
            log.info("chat reading: %d line(s) stored cut, now whole: %s", len(completed),
                     "; ".join(_said(yap.best) for yap in completed))  # fmt: skip
        return adopted, refused, completed

    def _why_not(self, line: ChatLine, dedup: Dedup) -> str | None:
        """Why a row seen twice still isn't stored, in words for the log; None: store it."""
        k = match_key(line)
        if k in self._far_like:
            return "like a line stored earlier"  # may be that one, still in the opened chat
        if dedup.misread_of(line) is not None:
            return "may be a known line read wrong"
        # a longer or cut reading of a stored line: a second line would be a repeat
        if dedup.piece_of(line) is not None or any(
            words >= 3 and k.startswith(s + " ") for s, words in self._near
        ):
            return "a piece of a stored line"
        return None

    def _really_unstored(self, ts: float, rows: list[ChatLine],
                         match: int | None) -> list[ChatLine]:  # fmt: skip
        """Seen-but-not-stored rows that really aren't stored (#504): not a line stored in the
        last minutes read differently (Dedup only knows its last 40), and each one once a match:
        Dedup forgets a row a minute out of sight, and seen again it was counted again. Kept
        frames of the match before and live ones take turns, so each match keeps its own."""
        if not rows:
            return []
        said = self._unstored_said.setdefault(match, [])
        for old in [m for m in self._unstored_said if m != match][:-2]:  # and 2 more at most
            del self._unstored_said[old]
        lines = sorted(self._store.lines_since(ts - STORED_FAR_S), key=lambda m: m.ts)
        far = [m for m in lines if m.ts < ts - UNSTORED_LOOK_S][-STORED_ROWS:]
        near = [m for m in lines if m.ts >= ts - UNSTORED_LOOK_S]
        stored = [text_key(m.hero or m.speaker_raw, m.text) for m in near]
        earlier = [text_key(m.hero or m.speaker_raw, m.text) for m in far]
        self._near = [(k, len(m.text.split())) for k, m in zip(stored + earlier, near + far,
                                                               strict=True)]  # fmt: skip
        self._far_like = set()
        found = []
        for line in rows:
            k = match_key(line)
            whole = len(line.text.split()) >= 3  # may be the start of a line with junk glued on
            if stored_as(k, said) or stored_as(k, stored, prefix=whole):
                continue
            if stored_as(k, earlier, prefix=whole):  # reported with this reason, never stored
                self._far_like.add(k)
            said.append(k)
            found.append(line)
        return found

    def _lines(self, image: np.ndarray, ocr_lines: list[OcrLine],
               recent: list[Yap] | None = None) -> tuple[list, list]:  # fmt: skip
        """(OCR lines with icons marked, chat lines with channel and who) of one read; recent:
        the yaps of the stream it belongs to (#597)."""
        recent = self._dedup.recent if recent is None else recent
        known = {**self._colours(), **self._seen_colours}
        read = without_input(ocr_lines, image)  # what you type isn't said yet (#254)
        read = channels.cut_glued(read, image, known)  # "gg 512" -> "gg" (#172)
        ocr = glyphs.mark(image, read)  # icons OCR can't spell become ◇ (#128)
        parsed = parse(
            ocr,
            has_icon=lambda box: channels.has_icon(image, box),  # (#329)
            clipped=lambda box, below: top_row.clipped(image, box, below),  # (#632)
        )
        learned = channels.learn(parsed, image)
        self._seen_colours.update(learned)  # e.g. HDR shifts them (#173)
        saved = self._colours()
        if "group" in learned and (
            "group" not in saved or channels.hue_distance(learned["group"], saved["group"]) > 10
        ):
            self._save_colours({"group": learned["group"]})  # seen only when someone uses it
        known = {**saved, **self._seen_colours}
        lines = channels.assign(parsed, image, known)
        lines = [replace(line, speaker=name) if (name := hero_speaker(line, recent))
                 else line for line in lines]  # a misread callout name (#424)  # fmt: skip
        return ocr, self._identity().apply(lines)

    def tidy_frame(self, kept: Kept) -> None:
        """One kept frame of a light match, read with the best quality and put next to the
        stored light lines (#336): better readings replace them, missed lines are inserted."""
        if self._tidy is None or self._tidy.match_id != kept.match_id:
            self._tidied()
            self._tidy = TidyMatch(kept.match_id)
            log.info("tidy: match %d started, %d frame(s) kept", kept.match_id,
                     len(self.tidy_frames) + 1)  # fmt: skip
        elif self._tidy_paused:
            log.info("tidy: match %d resumed, %d frame(s) left", kept.match_id,
                     len(self.tidy_frames) + 1)  # fmt: skip
        self._tidy_paused = False
        started = _cpu_now()
        tidy = self._tidy
        tidy.seen.append(kept.ts)
        _, lines = self._lines(kept.image, self._read_kept(kept.image, BEST))
        new, improved = tidy.dedup.update(kept.ts, lines)
        stored = self._store.match_lines(kept.match_id) if new else []
        for yap in new:
            placed = tidy.place(yap, stored)
            if placed is None:  # the light reader missed it: in at its real time
                player = self._link(yap)
                tidy.links[yap.id] = message_id = self._store.add_message(
                    ts=yap.first_seen, match_id=kept.match_id, player_id=player,
                    **self._named(yap, kept.image))  # fmt: skip
                self._save_picture(message_id, yap.first_seen, kept.image, yap.last.box)
                tidy.found += 1
                if yap.best.channel != "system":
                    self._on_player(player, kept.match_id, True)
            else:
                message, hands_off = placed
                tidy.links[yap.id] = None if hands_off else message.id
                self._tidy_fix(yap, message, kept)
        for yap in improved:
            if tidy.links.get(yap.id) is not None:
                self._tidy_fix(yap, self._store.message(tidy.links[yap.id]), kept)
        CPU.add("reading", _cpu_now() - started)
        if not len(self.tidy_frames):
            self._tidied()

    def _tidy_fix(self, yap: Yap, message, kept: Kept) -> None:
        fields = self._named(yap, kept.image, message)
        if message is None or self._tidy.links.get(yap.id) is None or not differs(message, fields):
            return
        self._store.update_message(message.id, player_id=self._link(yap), **fields)
        if yap.best is yap.last:  # its picture from this frame
            self._save_picture(message.id, message.ts, kept.image, yap.last.box)
        self._tidy.changed(message.id, fields)

    def _link(self, yap: Yap) -> int | None:
        speaker = yap.best.speaker if yap.best.channel != "system" else None
        return self._players.link(speaker, yap.first_seen, yap.best.confidence) if (
            self._players) else None  # fmt: skip

    def _tidied(self) -> None:
        """A match's tidy-up is done: light lines no best reading confirmed go (#432), then the
        log line and Live's note (#336)."""
        tidy, self._tidy = self._tidy, None
        if tidy is None:
            return
        stored = self._store.match_lines(tidy.match_id)
        doomed = tidy.unconfirmed(stored, self._store.hand_touched(tidy.match_id))
        if self._store.remove_lines(doomed) and self._players is not None:
            self._players.reload()  # its players went with them (#458)
        log.info("tidied match %d: %d fixed, %d found, %d removed (light readings the best reader "
                 "didn't confirm: repeats, pieces)", tidy.match_id, len(tidy.fixed), tidy.found,
                 len(doomed))  # fmt: skip
        self.tidied = (tidy.match_id, len(tidy.fixed), tidy.found)

    def _note_tidy_paused(self) -> None:
        """A tidy-up waits while the next match runs: said once (#432)."""
        if self._tidy is not None and len(self.tidy_frames) and not self._idle():
            if not self._tidy_paused:
                log.info("tidy: match %d paused, %d frame(s) left: a match runs",
                         self._tidy.match_id, len(self.tidy_frames))  # fmt: skip
            self._tidy_paused = True

    @property
    def menu(self) -> bool:
        """No match runs and the last reads found no chat: a menu, read every MENU_GAP_S."""
        return self._no_chat >= NO_CHAT_READS and self._idle()

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
        if self._players is not None and self._players.generation != self._players_seen:
            self._speakers.clear()  # a merge or a removal since: the ids may be gone (#458)
            self._players_seen = self._players.generation
        known = self._speakers.get(yap.id)
        if known is not None and known[0] == speaker:
            return known[1]
        pid = self._players.link(speaker, ts, yap.best.confidence) if self._players else None
        self._speakers[yap.id] = (speaker, pid)
        return pid

    def _named(self, yap: Yap, image: np.ndarray, stored=None) -> dict:
        """The yap's fields to store, its "◇" named where the row shows a known icon (#121).
        A name the stored line already has stays when this frame doesn't show the icon as well
        (a bright map behind it)."""
        fields = _fields(yap.best)
        if fields["has_glyphs"]:
            try:
                text = icons.name(fields["text"], row(image, yap.last.box))
            except Exception as error:  # a line without its icon's name is still a line
                side_work.failed("naming an icon", error)
                text = fields["text"]
            if stored is not None and glyphs.unnamed(stored.text) == text:
                text = stored.text
            fields["text"] = text
        return fields

    def _keep_picture(self, yap: Yap, image: np.ndarray) -> None:
        self._save_picture(self._stored[yap.id], yap.first_seen, image, yap.last.box)

    def _save_picture(self, message_id: int, ts: float, image: np.ndarray, box) -> None:
        """A line without its picture is still a line (#452); Read again says it has none."""
        if self._pictures is None:
            return
        try:
            self._pictures.save(message_id, ts, image, box)
        except Exception as error:
            side_work.failed("saving a line picture", error)

    def _count(self, spent: float) -> None:
        CPU.add("reading", spent)  # the per-part line (#302)
        self.read_frames += 1
        self.busy_s += spent
        self._load_busy += spent
        self._load_frames += 1
        now, cpu = time.monotonic(), cpu_parts.app_cpu()
        if now - self._load_since >= LOAD_LOG_S:  # the "< 5 % of one core" goal, checkable
            wall = now - self._load_since
            whole = 100 * (cpu - self._load_cpu) / wall
            # Above the goal: read every 3 s for a minute (chat stays ~9 s on screen, #249).
            self.busy = whole > CPU_GOAL
            modes = self._modes()
            log.info("chat reading: %d frames, %.0f ms CPU each%s; whole app: %.1f %% of a core;"
                     " %s", self._load_frames, 1000 * self._load_busy / self._load_frames,
                     f" ({modes})" if modes else "", whole, self._gap_words())  # fmt: skip
            if self.menu:  # how often the menu "changed" without chat: the goal is <= 6/min (#350)
                log.info("chat reading: no chat in the box between matches, reading every %g s;"
                         " %d changed frames in %.0f s", MENU_GAP_S, self._offered,
                         wall)  # fmt: skip
            self._load_since, self._load_cpu = now, cpu
            self._load_busy, self._load_frames, self._offered = 0.0, 0, 0
            self._held_back = False


def _cpu_now() -> float:
    """CPU seconds a read has cost up to now: this thread's, and the OCR child's (#563), which
    works for this thread only."""
    return time.thread_time() + cpu_parts.children()


def _said(line: ChatLine) -> str:
    return f"{line.speaker or ''}: {line.text}"[:50]


def _span(first: float, last: float) -> str:
    clock = time.strftime("%H:%M:%S", time.localtime(first))
    return f"{clock} to {time.strftime('%H:%M:%S', time.localtime(last))}"

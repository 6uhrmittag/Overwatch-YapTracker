"""Capture starts by itself when Overwatch appears and stops when it goes (#16). No buttons."""

import logging
import threading
import time
from collections.abc import Callable

from yaptracker import side_work
from yaptracker.capture.black import STARTUP_S
from yaptracker.capture.health import CaptureHealth
from yaptracker.capture.source import CaptureStalled, Frame, FrameSource

log = logging.getLogger(__name__)
# Covered longer than this: a gap record (#497). A line stays ~9 s on screen and is read every
# 1.5 s, so a shorter cover can't hide a whole line: it was read before or after.
COVER_GAP_S = 6.0
# A lost capture session (Windows ended it, or no picture came) is opened again at once, then
# every RETRY_S; after FAST_TRIES failed restarts with Overwatch in front, the screen is read
# instead (#506). Later failures wait longer and longer, as before.
RETRY_S, FAST_TRIES = 1.0, 5
# A session that gave pictures for this long worked: only then do failed restarts start over. A
# new session gets one picture at once, so "it gave a picture" alone doesn't prove it (#506).
HEALTHY_S = 30.0
# No picture for this long is a lost session: in a match the game always draws (#506); menus
# may send few pictures. Checked by the watchdog, not by the thread that handles the frames;
# for sources that say when they last had a picture (WGC; GDI too, never under its 10 s, #605).
MATCH_STALL_S, STALL_S = 3.0, 10.0
TICK_S, LATE_S = 0.5, 2.0  # the watchdog's tick, and when a late tick is logged
# A late tick means our threads didn't run (the game had the cores, #563), and the thread that
# notes pictures waited too: time the app didn't run doesn't count as time without a picture.
# From STARVED_S late, the app counts as starved for STARVED_FOR_S (#601): the picture thread may
# wait even when the tick is on time (Windows delivered a picture every 5 s in such matches), so
# a match's stall limit is STARVED_STALL_S then; a real stall is still noticed, a little later.
STARVED_S, STARVED_STALL_S = 1.0, 6.0
STARVED_FOR_S = 60.0  # a starved tick counts this long: the chat reader reads less often (#601)


class CaptureWatcher:
    """Polls for the game window; while it exists, feeds its frames to `on_frame`."""

    def __init__(
        self,
        find_window: Callable[[], int | None],
        open_source: Callable[[int], FrameSource],
        on_frame: Callable[[Frame], None] = lambda frame: None,
        poll_s: float = 2.0,
        paused: Callable[[], bool] = lambda: False,
        on_alive: Callable[[], None] = lambda: None,
        health: CaptureHealth | None = None,
        on_signals: Callable[[Frame], None] = lambda frame: None,
        on_closed: Callable[[], None] = lambda: None,
        clock: Callable[[], float] = time.monotonic,
        stall_s: Callable[[], float] = lambda: STALL_S,
        retry_s: float = RETRY_S,
        in_front: Callable[[int], bool] = lambda window: False,
        on_failing: Callable[[int], None] = lambda window: None,
        on_ended: Callable[[int, str], None] = lambda window, why: None,
        on_back: Callable[[], None] = lambda: None,
        startup_s: float = STARTUP_S,
        ran_before: Callable[[], float] = lambda: 0.0,
    ) -> None:
        self._find_window = find_window
        self._open_source = open_source
        self._on_frame = on_frame
        self._poll_s = poll_s
        self._paused = paused
        self._on_alive = on_alive  # every frame, paused or not: the evening is still going (#21)
        self._health = health  # gap records (#75)
        self._on_signals = on_signals  # match signals (#93); they run even while paused
        self._on_closed = on_closed  # Overwatch closed after capturing: the evening line (#379)
        self._failures = 0  # in a row; the retry wait grows with them
        self._stall_s, self._retry_s = stall_s, retry_s  # (#506)
        self._in_front = in_front  # Overwatch is the foreground window (#506)
        self._on_failing = on_failing  # restarts keep failing: read the screen instead (#506)
        self._front_failures = 0  # failed restarts in a row with Overwatch in front
        self._opened_at = 0.0
        self._window_since: float | None = None  # when Overwatch's window appeared (#560)
        self._startup_s = startup_s
        self._ran_before = ran_before  # Overwatch ran this long before we first saw it
        self._captured = False  # since Overwatch appeared: its closing is said (#560)
        self._stalled: tuple[FrameSource, str] | None = None  # set by the watchdog
        self._due = 0.0  # when the watchdog's next tick should come
        # (the last picture, seconds since then the app didn't run, said in the log) (#601)
        self._waited: tuple[float, float, bool] = (0.0, 0.0, False)
        self._starved_at: float | None = None
        # Diagnostics (#506): what the window did when a capture ended, once per lost stretch.
        self._on_ended, self._on_back = on_ended, on_back
        self._focus_window: int | None = None  # the last captured window, for focus changes
        self._in_focus: bool | None = None
        self._focus_lost_at: float | None = None  # wall clock, for the log
        self._focus_back_at: float | None = None
        # None, "lost" (diagnosed) or "back" (its first picture noted); over after HEALTHY_S of
        # pictures, so a session that dies after each picture is one stretch, not one a second
        self._stretch: str | None = None
        self._clock = clock
        self._covered_since: float | None = None  # another window over the chat box (#497)
        self.covered: str | None = None  # what covers it right now, for Live
        self._cover_gap = False
        self._stop = threading.Event()
        self._reopen = threading.Event()
        self._source: FrameSource | None = None
        self._thread: threading.Thread | None = None
        self.state = "waiting"  # waiting | capturing
        self.window: int | None = None  # the captured window while capturing
        self.frames = 0
        self.last_frame: Frame | None = None
        self.last_error: str | None = None  # shown in the Live view; capture health is #75

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="capture watcher", daemon=True)
        self._thread.start()
        threading.Thread(target=self._watch, name="capture watchdog", daemon=True).start()

    def snapshot(self, timeout: float = 2.0):
        """A full-size BGR frame of the game window right now, or None (#112). Blocks."""
        source = self._source
        if self.state != "capturing" or source is None or not hasattr(source, "snapshot"):
            return None
        return source.snapshot(timeout)

    def reopen(self) -> None:
        """Close the capture and open it again at once, e.g. on the screen instead (#236).
        Not a loss: no gap, no retry wait."""
        self._reopen.set()

    def stop(self) -> None:
        self._stop.set()
        if self._source is not None:
            self._source.close()
        if self._thread is not None:
            self._thread.join(timeout=5)  # nothing may write to the store after it closes

    def _run(self) -> None:
        """Supervises the capture: restarts it when it breaks, with growing waits (#75). It never
        ends but on stop (#457): a failing gap write or window lookup is logged and retried."""
        while not self._stop.is_set():
            try:
                return self._supervise()
            except Exception as error:
                side_work.failed("the capture supervisor", error, then="it goes on")
                self.state, self.window = "waiting", None
                self._stop.wait(self._poll_s)

    def _supervise(self) -> None:
        while not self._stop.is_set():
            window = self._find_window()
            if window is None:
                # it broke, or was being reopened, and then the game went: no more loss
                if self._failures or self._captured:
                    self._game_closed()
                self.state, self._failures, self._front_failures = "waiting", 0, 0
                self._captured = False
                self.last_error = self._stretch = None  # the next launch starts afresh
                self._focus_window = self._in_focus = None
                self._focus_lost_at = self._focus_back_at = self._window_since = None
                self._stop.wait(self._poll_s)
                continue
            if self._window_since is None:
                self._window_since = self._clock()
            try:
                self._capture(window)
                if self._stop.is_set():
                    return  # shutting down closed it: not a loss
                if self._reopen.is_set():
                    self._reopen.clear()
                    continue
                reason = "window_lost" if self._find_window() is not None else None
            except CaptureStalled as error:
                log.warning("capture stalled: %s", error)
                self.last_error, reason = str(error), "no_frames"
            except Exception as error:  # logged with traceback, shown, recorded, retried
                log.exception("capture failed")
                self.last_error, reason = str(error), "crash"
            self.state, self.window = "waiting", None
            if reason is None:
                self._game_closed()
                self._captured = False
                self._failures = self._front_failures = 0
                continue
            self._health_call("lost", reason)
            self._failures += 1
            if self._stretch is None:  # the first loss of a stretch: what was going on (#506)
                self._stretch = "lost"
                ended = "Windows ended the capture session"  # last_error may be older
                self._diagnose(window, ended if reason == "window_lost" else self.last_error or "")
            self._failing(window, lived=self._clock() - self._opened_at)
            self._stop.wait(self._retry_wait())

    def _retry_wait(self) -> float:
        """At once, then every second, then longer and longer (#506). Never more than one open a
        second: a session Windows ends right after each picture mustn't spin."""
        if self._failures == 1:
            return max(0.0, self._retry_s - (self._clock() - self._opened_at))
        if self._failures <= FAST_TRIES + 1:
            return self._retry_s
        return min(60.0, self._poll_s * 2 ** (self._failures - FAST_TRIES - 2))

    @property
    def game_window(self) -> int | None:
        """Overwatch's window as last captured, also between two captures of it (a restart);
        None once the game is gone. `window` is only set while a capture runs."""
        return self._focus_window

    def window_age(self) -> float | None:
        """Seconds since Overwatch's window appeared; None: no window."""
        since = self._window_since
        return None if since is None else self._clock() - since + self._ran_before()

    def _failing(self, window: int, lived: float = HEALTHY_S) -> None:
        """A restart that brought no picture, or only a few seconds of them, with Overwatch in
        front: FAST_TRIES of them in a row read the screen instead (#506). Minimised or
        alt-tabbed doesn't count; nor does the game's first minute, when it's still starting and
        its window may show nothing new for a while (#560)."""
        if self._failures < 2 and lived >= HEALTHY_S:
            return  # the first loss after a session that worked isn't a failed restart
        if (self.window_age() or 0.0) < self._startup_s:
            self._front_failures = 0
            self._failures = min(self._failures, FAST_TRIES + 1)  # no long waits from these
            return
        if not self._in_front(window):
            self._front_failures = 0
            return
        self._front_failures += 1
        if self._front_failures >= FAST_TRIES:
            self._front_failures = 0
            try:
                self._on_failing(window)
            except Exception as error:
                side_work.failed("switching to the screen", error, then="the capture goes on")

    def _diagnose(self, window: int, why: str) -> None:
        try:
            self._on_ended(window, why)
        except Exception as error:
            side_work.failed("noting why the capture ended", error, then="the capture goes on")

    def focus_note(self) -> str:
        """When Overwatch last lost and regained focus, for the capture-ended line (#506)."""
        lost, back = self._focus_lost_at, self._focus_back_at
        if lost is None:
            return "focus: not lost since the capture started"
        said = f"focus: lost {_clock_time(lost)}"
        return f"{said}, back {_clock_time(back)}" if back and back >= lost else f"{said}, not back"

    def _check_focus(self) -> None:
        """Overwatch losing focus is when Windows tends to drop its capture (#506): logged."""
        window = self._focus_window
        if window is None:
            return
        now, focus = time.time(), self._in_front(window)
        if self._in_focus is not None and focus != self._in_focus:
            if focus:
                self._focus_back_at = now
                lost = self._focus_lost_at
                log.info("capture: Overwatch in front again%s",
                         f" after {now - lost:.0f} s" if lost else "")  # fmt: skip
            else:
                self._focus_lost_at = now
                log.info("capture: Overwatch lost focus")
        self._in_focus = focus

    def _watch(self) -> None:
        """The watchdog (#506): its own thread, so frame handling, the database or the UI can't
        delay it. A capture that went quiet is closed; the supervisor opens it again."""
        self._due = self._clock() + TICK_S
        while not self._stop.wait(TICK_S):
            self._tick(self._clock())

    def _tick(self, now: float) -> None:
        late = max(0.0, now - self._due)
        if late > LATE_S:
            log.info("capture: watchdog tick %.1f s late", late)
        if late >= STARVED_S:
            self._starved_at = now
        try:
            self._check_stall(now, late)
            self._check_focus()
        except Exception as error:
            side_work.failed("the capture watchdog", error, then="it goes on")
        self._due = self._clock() + TICK_S  # after its own work: a slow close isn't lateness

    def starved(self) -> bool:
        """A watchdog tick came late within the last minute: the app waits for a core (#601)."""
        at = self._starved_at
        return at is not None and self._clock() - at < STARVED_FOR_S

    def _check_stall(self, now: float, late: float = 0.0) -> None:
        source = self._source
        last = getattr(source, "last_frame_at", None)  # when it last had a picture
        if source is None or last is None:
            return
        if self._stalled is not None and self._stalled[0] is source:
            return  # already closed; a stale one for an older session doesn't count
        last = max(last, self._opened_at)
        quiet = now - last
        _, away, said = self._waited if self._waited[0] == last else (last, 0.0, False)
        away += min(late, quiet)  # a starved app isn't a stalled window (#601)
        limit = max(self._stall_s(), getattr(source, "min_stall_s", 0.0))  # GDI: 10 s (#605)
        allowed = max(limit, STARVED_STALL_S) if self.starved() else limit
        if quiet - away > allowed:
            self._stalled = (source, f"no picture from the window for {allowed:g} s")
            source.close()  # the frame loop ends; the supervisor restarts it
            return
        starved = away >= STARVED_S or allowed > limit
        if quiet > limit and starved and not said:  # it would have restarted: once per stretch
            said = True
            log.info("capture: app starved %.1f s: no picture for %.1f s isn't taken for a stall",
                     away, quiet)  # fmt: skip
        if limit < STALL_S and quiet > COVER_GAP_S:
            # in a match, this long without a picture can hide a line: a gap, never a silent
            # hole. No restart; the next picture closes it.
            self._health_call("lost", "no_frames")
        self._waited = (last, away, said)

    def _back(self) -> None:
        try:
            self._on_back()
        except Exception as error:
            side_work.failed("noting that the capture is back", error, then="it goes on")

    def _game_closed(self) -> None:
        self._health_call("game_closed")
        try:
            self._on_closed()
        except Exception as error:
            side_work.failed("ending the match when the game closed", error, then="it goes on")

    def _cover(self, frame: Frame) -> None:
        """Not read; said once per cover; a cover over COVER_GAP_S is a gap (#497)."""
        self.last_frame = frame  # "What I see" shows what's in the way
        now, self.covered = self._clock(), frame.covered
        if self._covered_since is None:
            self._covered_since = now
            log.info("capture: chat box covered by another window - not reading")  # no title:
            # it may name a private document, and logs get pasted into issues
        elif not self._cover_gap and now - self._covered_since >= COVER_GAP_S:
            self._cover_gap = True
            self._health_call("lost", "no_frames")  # no usable picture (the DB has no "covered")

    def _uncover(self) -> None:
        if self._covered_since is not None:
            log.info("capture: chat box free again after %.0f s - reading",
                     self._clock() - self._covered_since)  # fmt: skip
            self._forget_cover()  # the next frame() closes a gap

    def _forget_cover(self) -> None:
        self._covered_since, self._cover_gap, self.covered = None, False, None

    def _health_call(self, method: str, *args) -> None:
        """Gap records (#75); one that can't be written never stops the capture (#457)."""
        if self._health is not None:
            try:
                getattr(self._health, method)(*args)
            except Exception as error:
                side_work.failed(f"recording '{method}'", error, then="the capture goes on")

    def _capture(self, window: int) -> None:
        self._stalled, self._opened_at, self._captured = None, self._clock(), True
        self._focus_window = window
        self._source = source = self._open_source(window)
        log.info("capturing window %s", window)
        self.state, self.window = "capturing", window
        was_paused = None
        try:
            for frame in source.frames():
                if self._stop.is_set():
                    break
                self.frames += 1
                self._on_alive()
                if frame.signals:
                    self._on_signals(frame)
                if self._reopen.is_set():
                    break
                if self._stretch == "lost":  # pictures again after a lost stretch (#506)
                    self._stretch = "back"
                    self._back()
                self.last_error, self._failures = None, 0
                if self._clock() - self._opened_at >= HEALTHY_S:
                    self._front_failures, self._stretch = 0, None
                paused = self._paused()
                if paused != was_paused:
                    self._health_call("paused", paused)
                    was_paused = paused
                if paused:  # the frame is dropped, not even previewed (#20)
                    self.last_frame = None
                    self._forget_cover()  # the pause is its own gap; a cover after it starts anew
                    continue
                if frame.covered:  # read from the screen with a window over it: not chat
                    self._cover(frame)
                    continue
                self._uncover()
                self._health_call("frame")
                self.last_frame = frame
                self._on_frame(frame)
            stalled, wanted = self._stalled, self._reopen.is_set() or self._stop.is_set()
            if stalled is not None and stalled[0] is source and not wanted:
                raise CaptureStalled(stalled[1])  # the watchdog closed it (#506)
        finally:
            source.close()
            self._source = None
            self._forget_cover()
            log.info("capture of window %s ended", window)


def fps(watcher: CaptureWatcher, window_s: float = 5.0) -> Callable[[], float]:
    """A tiny meter for the Live view: frames per second over the last few seconds."""
    samples: list[tuple[float, int]] = []

    def measure() -> float:
        now = time.monotonic()
        samples.append((now, watcher.frames))
        while samples and now - samples[0][0] > window_s:
            samples.pop(0)
        (t0, f0), (t1, f1) = samples[0], samples[-1]
        return (f1 - f0) / (t1 - t0) if t1 > t0 else 0.0

    return measure


def _clock_time(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))

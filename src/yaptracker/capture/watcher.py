"""Capture starts by itself when Overwatch appears and stops when it goes (#16). No buttons."""

import logging
import threading
import time
from collections.abc import Callable

from yaptracker.capture.health import CaptureHealth
from yaptracker.capture.source import CaptureStalled, Frame, FrameSource

log = logging.getLogger(__name__)


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
    ) -> None:
        self._find_window = find_window
        self._open_source = open_source
        self._on_frame = on_frame
        self._poll_s = poll_s
        self._paused = paused
        self._on_alive = on_alive  # every frame, paused or not: the evening is still going (#21)
        self._health = health  # gap records (#75)
        self._on_signals = on_signals  # match signals (#93); they run even while paused
        self._failures = 0  # in a row; the retry wait grows with them
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
        """Supervises the capture: restarts it when it breaks, with growing waits (#75)."""
        while not self._stop.is_set():
            window = self._find_window()
            if window is None:
                if self._failures:  # it broke and then the game went: no more loss
                    self._health_call("game_closed")
                self.state, self._failures = "waiting", 0
                self._stop.wait(self._poll_s)
                continue
            try:
                self._capture(window)
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
                self._health_call("game_closed")
                self._failures = 0
                continue
            self._health_call("lost", reason)
            self._failures += 1
            self._stop.wait(min(60.0, self._poll_s * 2 ** (self._failures - 1)))

    def _health_call(self, method: str, *args) -> None:
        if self._health is not None:
            getattr(self._health, method)(*args)

    def _capture(self, window: int) -> None:
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
                self.last_error, self._failures = None, 0
                paused = self._paused()
                if paused != was_paused:
                    self._health_call("paused", paused)
                    was_paused = paused
                if paused:  # the frame is dropped, not even previewed (#20)
                    self.last_frame = None
                    continue
                self._health_call("frame")
                self.last_frame = frame
                self._on_frame(frame)
        finally:
            source.close()
            self._source = None
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

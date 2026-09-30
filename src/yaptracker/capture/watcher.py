"""Capture starts by itself when Overwatch appears and stops when it goes (#16). No buttons."""

import logging
import threading
import time
from collections.abc import Callable

from yaptracker.capture.source import Frame, FrameSource

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
    ) -> None:
        self._find_window = find_window
        self._open_source = open_source
        self._on_frame = on_frame
        self._poll_s = poll_s
        self._paused = paused
        self._on_alive = on_alive  # every frame, paused or not: the evening is still going (#21)
        self._stop = threading.Event()
        self._source: FrameSource | None = None
        self.state = "waiting"  # waiting | capturing
        self.frames = 0
        self.last_frame: Frame | None = None
        self.last_error: str | None = None  # shown in the Live view; capture health is #75

    def start(self) -> None:
        threading.Thread(target=self._run, name="capture watcher", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        if self._source is not None:
            self._source.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            window = self._find_window()
            if window is None:
                self.state = "waiting"
                self._stop.wait(self._poll_s)
                continue
            try:
                self._capture(window)
            except Exception as error:  # logged with traceback and shown; retried next poll
                log.exception("capture failed")
                self.last_error = str(error)
            self.state = "waiting"
            self._stop.wait(self._poll_s)

    def _capture(self, window: int) -> None:
        self._source = source = self._open_source(window)
        log.info("capturing window %s", window)
        self.state, self.last_error = "capturing", None
        try:
            for frame in source.frames():
                if self._stop.is_set():
                    break
                self.frames += 1
                self._on_alive()
                if self._paused():  # paused: the frame is dropped, not even previewed (#20)
                    self.last_frame = None
                    continue
                self.last_frame = frame
                self._on_frame(frame)
        finally:
            source.close()
            self._source = None
            log.info("window %s is gone, waiting for Overwatch", window)


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

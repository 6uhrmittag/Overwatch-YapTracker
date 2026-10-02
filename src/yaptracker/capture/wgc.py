"""Windows Graphics Capture of one window, like OBS "Window Capture" (#16). Windows only."""

import contextlib
import logging
import queue
import sys
import threading
import time
from collections.abc import Callable, Iterator

from yaptracker.capture.source import CaptureStalled, Frame, Region
from yaptracker.capture.stats import CAPTURE

log = logging.getLogger(__name__)
_END = object()
# Capture settings and the Windows build that brought each one (GraphicsCaptureSession, #216).
# windows-capture refuses to start with a setting this Windows lacks: those are never passed.
SINCE = {
    "cursor_capture": (19041, "Windows 10 2004"),  # IsCursorCaptureEnabled
    "draw_border": (20348, "Windows 11"),  # IsBorderRequired
    "minimum_update_interval": (26100, "Windows 11 24H2"),  # MinUpdateInterval
}
CANNOT = {
    "cursor_capture": "leave the mouse pointer out",
    "draw_border": "hide the yellow border",
    "minimum_update_interval": "slow the capture down",
}


def windows_build() -> int:
    return sys.getwindowsversion().platform_version[2] if sys.platform == "win32" else 0


def capture_options(build: int, fps: float) -> tuple[dict, list[str]]:
    """What to ask WGC for on this Windows, and what it can't do (left at Windows' default)."""
    wanted = {"cursor_capture": False, "draw_border": False,
              "minimum_update_interval": int(1000 / fps)}  # fmt: skip
    usable = {name: value for name, value in wanted.items() if build >= SINCE[name][0]}
    return usable, [name for name in wanted if name not in usable]


class WgcFrameSource:
    """Frames of one window at up to `fps`, cropped to the chat box before anything is copied."""

    def __init__(
        self,
        hwnd: int,
        region_for: Callable[[int, int], Region],
        fps: float = 4.0,
        stall_s: float = 10.0,
        signals_for: Callable[[int, int], dict[str, Region]] = lambda w, h: {},
        signals_every_s: float = 1.0,
        overview_every_s: float = 5.0,
    ):
        self._signals_for = signals_for
        self._signals_every_s, self._overview_every_s = signals_every_s, overview_every_s
        self._signals_at = self._overview_at = 0.0
        self._queue: queue.Queue = queue.Queue(maxsize=2)  # a slow reader gets the newest frames
        self._snapshot_wanted, self._snapshot_ready = threading.Event(), threading.Event()
        self._snapshot = None
        self._stall_s = stall_s
        self._closed = threading.Event()
        self._start = time.monotonic()
        self._region_for = region_for
        # Our own gate: without minimum_update_interval (before Windows 11 24H2) every frame the
        # game draws arrives here. A bit under 1/fps, so Windows' own 4 fps aren't cut.
        self._gap_s, self._used_at = 0.9 / fps, -1.0
        build = windows_build()
        options, dropped = capture_options(build, fps)
        CAPTURE.asked_fps, CAPTURE.cannot = fps, [CANNOT[name] for name in dropped]
        if dropped:
            log.info("capture: Windows build %d can't %s; those settings aren't asked for", build,
                     ", ".join(CANNOT[name] for name in dropped))  # fmt: skip
        try:
            self._control = self._capture(hwnd, options).start_free_threaded()
        except Exception as error:  # a setting this Windows refuses after all: none of them
            log.warning(
                "capture didn't start with %s (%s), trying without settings", options, error
            )
            CAPTURE.cannot = list(CANNOT.values())
            self._control = self._capture(hwnd, {}).start_free_threaded()

    def _capture(self, hwnd: int, options: dict):
        from windows_capture import WindowsCapture

        capture = WindowsCapture(window_hwnd=hwnd, **options)

        @capture.event
        def on_frame_arrived(frame, control) -> None:
            if self._closed.is_set():
                control.stop()
                return
            now = time.monotonic()
            if now - self._used_at < self._gap_s and not self._snapshot_wanted.is_set():
                CAPTURE.skipped()  # before the frame buffer is touched (#216)
                return
            self._used_at = now
            started = time.perf_counter()
            if self._snapshot_wanted.is_set():  # Calibrate asked for the whole window (#112)
                self._snapshot = frame.frame_buffer[:, :, :3].copy()
                self._snapshot_wanted.clear()
                self._snapshot_ready.set()
            region = self._region_for(frame.width, frame.height)
            # BGRA -> BGR, and copy only the chat box: the capture buffer is reused.
            chat = region.crop(frame.frame_buffer)[:, :, :3].copy()
            signals = {}
            if now - self._signals_at >= self._signals_every_s:  # small crops, once a second
                self._signals_at = now
                signals = {
                    name: r.crop(frame.frame_buffer)[:, :, :3].copy()
                    for name, r in self._signals_for(frame.width, frame.height).items()
                }
                if now - self._overview_at >= self._overview_every_s:  # debug samples (#63)
                    self._overview_at = now
                    signals["overview"] = frame.frame_buffer[::4, ::4, :3].copy()
            self._put(Frame(now - self._start, chat, signals))
            CAPTURE.frame(time.perf_counter() - started)  # what Windows delivers, and our cost

        @capture.event
        def on_closed() -> None:
            self._put(_END)

        return capture

    def _put(self, item: object) -> None:
        while True:
            try:
                self._queue.put_nowait(item)
                return
            except queue.Full:
                with contextlib.suppress(queue.Empty):
                    self._queue.get_nowait()  # drop the oldest frame

    def snapshot(self, timeout: float = 2.0):
        """One full-size BGR frame of the window, or None if none arrives (e.g. minimised)."""
        self._snapshot_ready.clear()
        self._snapshot_wanted.set()
        return self._snapshot if self._snapshot_ready.wait(timeout) else None

    def frames(self) -> Iterator[Frame]:
        while True:
            try:
                item = self._queue.get(timeout=self._stall_s)
            except queue.Empty:
                raise CaptureStalled(
                    f"no picture from the window for {self._stall_s:.0f} s"
                ) from None
            if item is _END:
                return
            yield item

    def close(self) -> None:
        self._closed.set()
        if not self._control.is_finished():
            self._control.stop()
        self._put(_END)

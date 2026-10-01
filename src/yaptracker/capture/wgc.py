"""Windows Graphics Capture of one window, like OBS "Window Capture" (#16). Windows only."""

import contextlib
import logging
import queue
import threading
import time
from collections.abc import Callable, Iterator

from yaptracker.capture.source import CaptureStalled, Frame, Region

log = logging.getLogger(__name__)
_END = object()


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
    ):
        self._signals_for = signals_for
        self._signals_every_s = signals_every_s
        self._signals_at = 0.0
        self._queue: queue.Queue = queue.Queue(maxsize=2)  # a slow reader gets the newest frames
        self._stall_s = stall_s
        self._closed = threading.Event()
        self._start = time.monotonic()
        self._region_for = region_for
        try:
            self._control = self._capture(hwnd, fps, draw_border=False).start_free_threaded()
        except Exception as error:  # hiding the yellow border needs Windows 11; Windows 10 shows it
            log.warning("capture border can't be hidden on this Windows (%s), keeping it", error)
            self._control = self._capture(hwnd, fps, draw_border=None).start_free_threaded()

    def _capture(self, hwnd: int, fps: float, draw_border: bool | None):
        from windows_capture import WindowsCapture

        capture = WindowsCapture(cursor_capture=False, draw_border=draw_border, window_hwnd=hwnd,
                                 minimum_update_interval=int(1000 / fps))  # fmt: skip

        @capture.event
        def on_frame_arrived(frame, control) -> None:
            if self._closed.is_set():
                control.stop()
                return
            region = self._region_for(frame.width, frame.height)
            # BGRA -> BGR, and copy only the chat box: the capture buffer is reused.
            chat = region.crop(frame.frame_buffer)[:, :, :3].copy()
            now = time.monotonic()
            signals = {}
            if now - self._signals_at >= self._signals_every_s:  # small crops, once a second
                self._signals_at = now
                signals = {
                    name: r.crop(frame.frame_buffer)[:, :, :3].copy()
                    for name, r in self._signals_for(frame.width, frame.height).items()
                }
            self._put(Frame(now - self._start, chat, signals))

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

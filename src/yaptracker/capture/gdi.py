"""Chat box capture with GDI, for Windows without WGC's rate setting (#248). Windows only.

Before Windows 11 24H2, WGC sends every frame the game draws, and windows-capture copies each one
from the graphics card before our callback can skip it: measured ~2.5 ms CPU per delivered frame,
at ~140 fps a full core on Void's PC, and a GPU readback per game frame. This grabs only what's
read - the chat box 4 times a second, the signal strips once a second, a small overview every 5 s
- with BitBlt from the screen, like the Snipping Tool (CLAUDE.md capture Fallback 2): ~0.9 ms
per chat box. The screen, not the window: something on top of the chat box is read too.
"""

import contextlib
import ctypes
import logging
import queue
import threading
import time
from collections.abc import Callable, Iterator
from ctypes import wintypes

import numpy as np

from yaptracker.capture.source import CaptureStalled, Frame, Region
from yaptracker.capture.stats import CAPTURE

log = logging.getLogger(__name__)
_END = object()
_SRCCOPY = 0x00CC0020
_PER_MONITOR_AWARE_V2 = -4  # DPI_AWARENESS_CONTEXT: real pixels, whatever the scaling


class _BitmapInfo(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD), ("bmiColors", wintypes.DWORD * 3)]  # fmt: skip


class ScreenGrabber:
    """BitBlt from the screen into a bitmap we can read. One per thread (its DPI awareness)."""

    def __init__(self) -> None:
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetThreadDpiAwarenessContext(_PER_MONITOR_AWARE_V2)
        user32.GetDC.restype = wintypes.HDC
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(_BitmapInfo),
                                           wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                           wintypes.HANDLE, wintypes.DWORD]  # fmt: skip
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int,
                                 wintypes.DWORD]  # fmt: skip
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi32.DeleteDC.argtypes = [wintypes.HDC]
        self._user32, self._gdi32 = user32, gdi32
        self._screen = user32.GetDC(None)
        self._memory = gdi32.CreateCompatibleDC(self._screen)
        self._bitmaps: dict[tuple[int, int], tuple[int, np.ndarray]] = {}

    def _bitmap(self, width: int, height: int) -> tuple[int, np.ndarray]:
        if (width, height) not in self._bitmaps:
            info = _BitmapInfo(biSize=40, biWidth=width, biHeight=-height, biPlanes=1,
                               biBitCount=32)  # fmt: skip  # top-down BGRA
            bits = ctypes.c_void_p()
            handle = self._gdi32.CreateDIBSection(self._screen, ctypes.byref(info), 0,
                                                  ctypes.byref(bits), None, 0)  # fmt: skip
            if not handle:
                raise OSError("CreateDIBSection failed")
            buffer = (ctypes.c_uint8 * (width * height * 4)).from_address(bits.value)
            self._bitmaps[(width, height)] = (handle, np.frombuffer(buffer, np.uint8)
                                              .reshape(height, width, 4))  # fmt: skip
        return self._bitmaps[(width, height)]

    def grab(self, x: int, y: int, width: int, height: int) -> np.ndarray:
        """That part of the screen (screen pixels), BGR, a copy of its own."""
        handle, pixels = self._bitmap(width, height)
        self._gdi32.SelectObject(self._memory, handle)
        if not self._gdi32.BitBlt(self._memory, 0, 0, width, height, self._screen, x, y,
                                  _SRCCOPY):  # fmt: skip
            raise OSError("BitBlt failed")
        self._gdi32.GdiFlush()
        return pixels[:, :, :3].copy()

    def close(self) -> None:
        for handle, _ in self._bitmaps.values():
            self._gdi32.DeleteObject(handle)
        self._gdi32.DeleteDC(self._memory)
        self._user32.ReleaseDC(None, self._screen)


def client_area(hwnd: int) -> tuple[int, int, int, int] | None:
    """The window's inside on the screen (x, y, width, height), None while it's minimised."""
    user32 = ctypes.windll.user32
    if not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):
        return None
    rect, origin = wintypes.RECT(), wintypes.POINT(0, 0)
    user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(origin))
    if rect.right <= 0 or rect.bottom <= 0:
        return None
    return origin.x, origin.y, rect.right, rect.bottom


class GdiFrameSource:
    """The chat box of one window at `fps`, plus the signal strips and an overview, via GDI.
    Same interface as WgcFrameSource."""

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
        self._hwnd, self._region_for, self._signals_for = hwnd, region_for, signals_for
        self._gap_s, self._signals_every_s = 1.0 / fps, signals_every_s
        self._overview_every_s, self._stall_s = overview_every_s, stall_s
        self._queue: queue.Queue = queue.Queue(maxsize=2)
        self._snapshot_wanted, self._snapshot_ready = threading.Event(), threading.Event()
        self._snapshot = None
        self._closed = threading.Event()
        self._start = time.monotonic()
        CAPTURE.asked_fps, CAPTURE.how = fps, "GDI, chat box only"
        self._thread = threading.Thread(target=self._run, name="gdi capture", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        grabber = ScreenGrabber()
        signals_at = overview_at = 0.0
        try:
            while not self._closed.is_set():
                started = time.perf_counter()
                area = client_area(self._hwnd)
                if area is None:  # minimised or gone: no pictures, the stall check notices
                    self._closed.wait(self._gap_s)
                    continue
                sx, sy, width, height = area
                if self._snapshot_wanted.is_set():  # Calibrate asked for the whole window (#112)
                    self._snapshot = grabber.grab(sx, sy, width, height)
                    self._snapshot_wanted.clear()
                    self._snapshot_ready.set()
                r = self._region_for(width, height)
                chat = grabber.grab(sx + r.x, sy + r.y, r.width, r.height)
                now = time.monotonic()
                signals = {}
                if now - signals_at >= self._signals_every_s:
                    signals_at = now
                    signals = {name: grabber.grab(sx + s.x, sy + s.y, s.width, s.height)
                               for name, s in self._signals_for(width, height).items()}  # fmt: skip
                    if now - overview_at >= self._overview_every_s:  # debug samples (#63)
                        overview_at = now
                        signals["overview"] = grabber.grab(sx, sy, width, height)[::4, ::4].copy()
                self._put(Frame(now - self._start, chat, signals))
                spent = time.perf_counter() - started
                CAPTURE.frame(spent)
                self._closed.wait(max(0.0, self._gap_s - spent))
        except Exception:
            log.exception("GDI capture failed")
        finally:
            grabber.close()
            self._put(_END)

    def _put(self, item: object) -> None:
        while True:
            try:
                self._queue.put_nowait(item)
                return
            except queue.Full:
                with contextlib.suppress(queue.Empty):
                    self._queue.get_nowait()  # drop the oldest frame

    def snapshot(self, timeout: float = 2.0):
        """One full-size BGR picture of the window, or None (e.g. minimised)."""
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
        self._thread.join(timeout=2)

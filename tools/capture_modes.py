"""Which way of capturing keeps Overwatch uncapped? (spike #229) Windows only, run by hand.

    python tools/capture_modes.py [--seconds 90] [--modes window,monitor,dxgi,duty]

Run it with YapTracker closed, Overwatch's performance overlay on (Options -> Video -> Display
performance stats) and the game standing still (practice range, same spot): the scene should
change as little as possible between the modes. Each mode captures the way it would in the
app (4 frames a second) and reads Overwatch's own FPS counter from what it captures, every 5 s:

    window   WGC window capture, as YapTracker does today
    monitor  WGC capture of the monitor Overwatch is on (CLAUDE.md capture Fallback 1)
    dxgi     DXGI desktop duplication of that monitor
    duty     WGC window capture started for one frame every 5 s, stopped in between

Read-only screen capture like OBS; the game process is never touched. Prints one line per
mode: median and p10 of the game's FPS, and the frames per second Windows sent.
"""

import argparse
import ctypes
import statistics
import sys
import threading
import time
from ctypes import wintypes

import numpy as np

from yaptracker.capture.window import find_overwatch
from yaptracker.game_fps import fps_box, overlay_regions, parse_fps
from yaptracker.ocr.engine import RapidOcrEngine

FPS = 4.0
READ_EVERY_S = 5.0


def monitor_index(hwnd: int) -> int:
    """windows-capture's 1-based monitor index (EnumDisplayMonitors order) of the window."""
    user32 = ctypes.windll.user32
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    target, found = user32.MonitorFromWindow(hwnd, 2), []
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                  ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)  # fmt: skip
    user32.EnumDisplayMonitors(None, None, callback(lambda m, *_: found.append(m) or True), 0)
    return found.index(target) + 1


def to_bgr(frame: np.ndarray) -> np.ndarray:
    if frame.dtype == np.float16:  # HDR duplication: linear scRGB, RGBA
        rgb = np.clip(frame[:, :, :3].astype(np.float32), 0, 1) ** (1 / 2.2)
        return np.ascontiguousarray((rgb[:, :, ::-1] * 255).astype(np.uint8))
    return np.ascontiguousarray(frame[:, :, :3])


class Meter:
    def __init__(self) -> None:
        self.engine, self.values, self.frames, self._read_at = RapidOcrEngine(), [], 0, 0.0

    def frame(self, image: np.ndarray) -> None:
        self.frames += 1
        now = time.monotonic()
        if now - self._read_at < READ_EVERY_S:
            return
        self._read_at = now
        height, width = image.shape[:2]
        box = fps_box(overlay_regions(width, height)["fps"].crop(image), height)
        value = parse_fps(self.engine.read_line(box)) if box is not None else None
        if value is not None:
            self.values.append(value)


def run_wgc(meter: Meter, seconds: float, **target) -> None:
    from windows_capture import WindowsCapture

    done, last = threading.Event(), {"at": 0.0}
    capture = WindowsCapture(cursor_capture=None, draw_border=None, **target)

    @capture.event
    def on_frame_arrived(frame, control) -> None:
        if done.is_set():
            control.stop()
            return
        now = time.monotonic()
        if now - last["at"] < 0.9 / FPS:  # the app's own gate (#216)
            return
        last["at"] = now
        meter.frame(to_bgr(frame.frame_buffer))

    @capture.event
    def on_closed() -> None:
        done.set()

    control = capture.start_free_threaded()
    time.sleep(seconds)
    done.set()
    if not control.is_finished():
        control.stop()


def run_dxgi(meter: Meter, seconds: float, monitor: int) -> None:
    from windows_capture import DxgiDuplicationSession

    session, end = DxgiDuplicationSession(monitor), time.monotonic() + seconds
    while time.monotonic() < end:
        frame = session.acquire_frame(timeout_ms=100)
        if frame is not None:
            meter.frame(to_bgr(frame.to_numpy()))
        time.sleep(1 / FPS)


def run_duty(meter: Meter, seconds: float, hwnd: int) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        before = meter.frames
        meter._read_at = 0.0  # every grab is read
        grab_end = time.monotonic() + 2
        while meter.frames == before and time.monotonic() < grab_end:
            run_wgc(meter, 0.3, window_hwnd=hwnd)
        time.sleep(READ_EVERY_S)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=90.0, help="per mode")
    parser.add_argument("--modes", default="window,monitor,dxgi,duty")
    args = parser.parse_args()
    if sys.platform != "win32":
        sys.exit("Windows only: it captures Overwatch.")
    hwnd = find_overwatch()
    if hwnd is None:
        sys.exit("Start Overwatch first (borderless windowed, performance overlay on).")
    monitor = monitor_index(hwnd)
    print(f"Overwatch is on monitor {monitor}; {args.seconds:.0f} s per mode")
    for mode in args.modes.split(","):
        meter, started = Meter(), time.monotonic()
        try:
            if mode == "window":
                run_wgc(meter, args.seconds, window_hwnd=hwnd)
            elif mode == "monitor":
                run_wgc(meter, args.seconds, monitor_index=monitor)
            elif mode == "dxgi":
                run_dxgi(meter, args.seconds, monitor)
            elif mode == "duty":
                run_duty(meter, args.seconds, hwnd)
        except Exception as error:  # a mode this PC can't do: say so, go on
            print(f"{mode:8} failed: {error}")
            continue
        values, spent = meter.values, time.monotonic() - started
        if not values:
            print(f"{mode:8} no FPS read (is the overlay on?), {meter.frames / spent:.1f} frames/s")
            continue
        p10 = float(np.percentile(values, 10))
        print(f"{mode:8} game fps median {statistics.median(values):.0f}, p10 {p10:.0f}, "
              f"n={len(values)}; {meter.frames / spent:.1f} frames/s used")  # fmt: skip


if __name__ == "__main__":
    main()

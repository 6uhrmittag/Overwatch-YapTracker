"""GDI capture for Windows without the rate setting (#248): a real window, read from the screen.
Windows only; CI runs this on both Windows runners."""

import ctypes
import subprocess
import sys
import time

import pytest

from yaptracker.capture.source import Region

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="GDI needs Windows")


def test_gdi_reads_the_chat_box_signals_and_a_snapshot_of_a_real_window():
    from yaptracker.capture.gdi import GdiFrameSource, client_area

    notepad = subprocess.Popen(["notepad.exe"])
    try:
        hwnd = None
        for _ in range(100):
            hwnd = ctypes.windll.user32.FindWindowW("Notepad", None)
            if hwnd:
                break
            time.sleep(0.1)
        assert hwnd, "Notepad window not found"
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.5)
        x, y, width, height = client_area(hwnd)
        assert width > 100 and height > 100
        corner = {"corner": Region(0, 0, 8, 8)}
        source = GdiFrameSource(hwnd, lambda w, h: Region(0, 0, w // 2, h // 2), fps=4,
                                signals_for=lambda w, h: corner)  # fmt: skip
        try:
            frames = source.frames()
            first, second = next(frames), next(frames)
            whole = source.snapshot(3.0)
        finally:
            source.close()
        assert first.image.shape == (height // 2, width // 2, 3)
        assert first.image.max() > 0, "GDI read a black picture"
        assert first.signals["corner"].shape == (8, 8, 3)  # the strips ride along once a second
        assert first.signals["overview"].shape[2] == 3
        assert second.ts - first.ts == pytest.approx(0.25, abs=0.15)  # 4 a second
        assert whole is not None and whole.shape == (height, width, 3)
    finally:
        notepad.kill()


def test_gdi_grabs_twice_a_second_and_once_while_the_chat_is_quiet():
    """#319: each grab makes the game wait for the screen, so fewer of them on Windows 10."""
    from yaptracker.capture.gdi import GDI_FPS, QUIET_FPS, GdiFrameSource

    assert (GDI_FPS, QUIET_FPS) == (2.0, 1.0)
    notepad = subprocess.Popen(["notepad.exe"])
    try:
        hwnd = None
        for _ in range(100):
            hwnd = ctypes.windll.user32.FindWindowW("Notepad", None)
            if hwnd:
                break
            time.sleep(0.1)
        assert hwnd, "Notepad window not found"
        quiet = {"on": False}
        source = GdiFrameSource(hwnd, lambda w, h: Region(0, 0, 64, 64),
                                quiet=lambda: quiet["on"])  # fmt: skip
        try:
            frames = source.frames()
            busy = [next(frames).ts for _ in range(3)]
            quiet["on"] = True
            next(frames)  # the wait already started at the busy pace
            calm = [next(frames).ts for _ in range(3)]
        finally:
            source.close()
        assert busy[2] - busy[0] == pytest.approx(1.0, abs=0.3)  # 2 a second
        assert calm[2] - calm[0] == pytest.approx(2.0, abs=0.4)  # 1 a second
    finally:
        notepad.kill()


def test_a_minimised_window_sends_nothing():
    from yaptracker.capture.gdi import client_area

    assert client_area(0) is None  # no window: no area, the stall check takes over


def tk_window(title: str, x: int, y: int, colour: str) -> tuple[subprocess.Popen, int]:
    """A plain window with a known title at (x, y), 500 x 300; returns (process, hwnd)."""
    code = (f"import tkinter as tk; r = tk.Tk(); r.title({title!r}); "
            f"r.geometry('500x300+{x}+{y}'); r.configure(bg={colour!r}); "
            "r.attributes('-topmost', True); r.mainloop()")  # fmt: skip
    process = subprocess.Popen([sys.executable, "-c", code])
    deadline = time.monotonic() + 60  # a cold Tk start on a busy runner (#487)
    while time.monotonic() < deadline:
        if hwnd := ctypes.windll.user32.FindWindowW(None, title):
            time.sleep(0.5)  # drawn
            return process, hwnd
        assert process.poll() is None, f"{title} ended"
        time.sleep(0.1)
    raise AssertionError(f"{title} didn't open")


def test_a_window_on_top_of_the_box_is_found_and_the_frame_marked():
    """#497: read from the screen, another window over the chat box isn't chat."""
    from yaptracker.capture.cover import covering
    from yaptracker.capture.gdi import GdiFrameSource, client_area

    under, under_hwnd = tk_window("yaptracker-under", 100, 100, "navy")
    over = None
    try:
        x, y, width, height = client_area(under_hwnd)
        box = Region(x, y, width // 2, height // 2)
        assert covering(under_hwnd, box) is None  # nothing on top yet
        over, _ = tk_window("yaptracker-over", 150, 150, "orange")  # later topmost: above
        assert covering(under_hwnd, box) == "yaptracker-over"
        source = GdiFrameSource(under_hwnd, lambda w, h: Region(0, 0, w // 2, h // 2), fps=4)
        try:
            frame = next(source.frames())
        finally:
            source.close()
        assert frame.covered == "yaptracker-over"
    finally:
        under.kill()
        if over is not None:
            over.kill()

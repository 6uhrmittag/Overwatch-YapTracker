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


def test_a_minimised_window_sends_nothing():
    from yaptracker.capture.gdi import client_area

    assert client_area(0) is None  # no window: no area, the stall check takes over

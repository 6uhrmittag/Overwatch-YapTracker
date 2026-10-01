"""Real WGC capture of a real window. Windows only; CI runs this on the Windows runner."""

import ctypes
import subprocess
import sys
import time

import pytest

from yaptracker.capture.source import Region

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="WGC needs Windows")


def test_wgc_captures_a_window_cropped_to_the_region():
    from yaptracker.capture.wgc import WgcFrameSource

    notepad = subprocess.Popen(["notepad.exe"])
    try:
        hwnd = None
        for _ in range(100):
            hwnd = ctypes.windll.user32.FindWindowW("Notepad", None)
            if hwnd:
                break
            time.sleep(0.1)
        assert hwnd, "Notepad window not found"
        from yaptracker.capture.window import has_title_bar

        assert has_title_bar(hwnd)  # a normal window: what setup warns about for Overwatch (#76)
        corner = {"corner": Region(0, 0, 8, 8)}
        source = WgcFrameSource(
            hwnd, lambda w, h: Region(0, 0, w // 2, h // 2), fps=4, signals_for=lambda w, h: corner
        )
        try:
            frame = next(source.frames())
        finally:
            source.close()
        assert frame.image.ndim == 3 and frame.image.shape[2] == 3
        assert frame.image.shape[0] > 10 and frame.image.shape[1] > 10
        assert frame.image.max() > 0, "capture delivered a black frame"
        # Signal crops and the debug overview (#63) ride along with the first frame.
        assert frame.signals["corner"].shape == (8, 8, 3)
        assert frame.signals["overview"].shape[2] == 3
    finally:
        notepad.kill()


def test_no_overwatch_means_no_window():
    from yaptracker.capture.window import find_overwatch

    assert find_overwatch() is None

"""Real WGC capture of a real window. Windows only; CI runs this on the Windows runner."""

import ctypes
import subprocess
import sys
import threading
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
            from yaptracker.capture import wgc

            # Started with only what this Windows can do (#216): on Server 2022 / Windows 10
            # without the rate setting, gated by us.
            _, dropped = wgc.capture_options(wgc.windows_build(), 4)
            assert wgc.CAPTURE.cannot == [wgc.CANNOT[name] for name in dropped]
            frame = next(source.frames())
            # Calibrate's screenshot of the whole window (#112). WGC only sends a frame when
            # the window repaints - Overwatch always does, a resting Notepad needs a nudge.
            taken = {}
            asking = threading.Thread(target=lambda: taken.update(whole=source.snapshot(3.0)))
            asking.start()
            while asking.is_alive():
                ctypes.windll.user32.InvalidateRect(hwnd, None, True)
                asking.join(0.1)
        finally:
            source.close()
        # the whole window, not the crop (Notepad may still settle by a few px in between)
        assert taken["whole"] is not None and taken["whole"].shape[0] >= frame.image.shape[0] * 1.8
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


def test_front_window_and_fullscreen_checks_answer():
    """#217: the checks behind "Overwatch is probably in Fullscreen" run on real Windows."""
    from yaptracker.capture.window import exclusive_fullscreen, in_front

    desktop = ctypes.windll.user32.GetDesktopWindow()
    assert in_front(desktop) in (True, False)
    assert exclusive_fullscreen(desktop) is False  # nothing in exclusive Fullscreen on CI

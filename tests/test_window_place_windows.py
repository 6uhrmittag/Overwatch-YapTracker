"""The app window's place on a real window (#253). Windows only; CI runs it."""

import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="window placement needs Windows")


def test_a_window_goes_back_to_its_place_and_maximised_state():
    import ctypes

    from yaptracker.window_place import Place, apply, read, screens

    notepad = subprocess.Popen(["notepad.exe"])
    try:
        hwnd = None
        for _ in range(100):
            hwnd = ctypes.windll.user32.FindWindowW("Notepad", None)
            if hwnd:
                break
            time.sleep(0.1)
        assert hwnd, "notepad didn't open"
        assert screens()
        place = Place((120, 90, 700, 500), (120, 90, 700, 500))
        apply(hwnd, place)
        time.sleep(0.3)
        assert read(hwnd).rect == place.rect and not read(hwnd).maximized
        apply(hwnd, Place(place.rect, place.normal, maximized=True))
        time.sleep(0.3)
        back = read(hwnd)
        assert back.maximized and back.normal[2:] == (700, 500)
    finally:
        notepad.kill()


def test_keep_restores_the_saved_place_then_saves_a_move(tmp_path, monkeypatch):
    """The app's start path on a real window: back at the saved place, and a move is saved."""
    import ctypes
    import threading
    from dataclasses import asdict

    from yaptracker import config, paths
    from yaptracker.window_place import LATE_S, POLL_S, SETTLE_S, Place, keep, read

    monkeypatch.setattr(paths, "config_file", lambda: tmp_path / "config.json")
    saved = Place((200, 150, 640, 480), (200, 150, 640, 480))
    config.save_window_place(asdict(saved))
    notepad = subprocess.Popen(["notepad.exe"])
    stop = threading.Event()
    try:
        hwnd = None
        for _ in range(100):
            hwnd = ctypes.windll.user32.FindWindowW("Notepad", None)
            if hwnd:
                break
            time.sleep(0.1)
        assert hwnd, "notepad didn't open"
        threading.Thread(target=keep, args=(lambda: hwnd, False, stop), daemon=True).start()
        time.sleep(LATE_S + 0.5)  # the restore checks itself until LATE_S (#299, #365)
        assert read(hwnd).rect == saved.rect  # back where it was
        # within the runner's small screen: a place that sticks out would be clamped (#299)
        ctypes.windll.user32.SetWindowPos(hwnd, None, 300, 120, 600, 400, 0x0014)
        time.sleep(2 * POLL_S + SETTLE_S + 0.5)
        assert Place.from_dict(config.window_place()).rect == (300, 120, 600, 400)
    finally:
        stop.set()
        notepad.kill()


def test_monitors_report_their_work_area_and_scaling():
    from yaptracker.window_place import monitors

    found = monitors()
    assert found
    for m in found:
        x, y, w, h = m.rect
        wx, wy, ww, wh = m.work
        assert x <= wx and y <= wy and wx + ww <= x + w and wy + wh <= y + h
        assert m.dpi >= 96


def test_a_window_is_described_with_its_dpi_and_moved_without_resizing():
    """The restore's diagnosis (#365) works on a real window, and a move keeps the size."""
    import ctypes

    from yaptracker.window_place import Place, apply, describe, move, read

    notepad = subprocess.Popen(["notepad.exe"])
    try:
        hwnd = None
        for _ in range(100):
            hwnd = ctypes.windll.user32.FindWindowW("Notepad", None)
            if hwnd:
                break
            time.sleep(0.1)
        assert hwnd, "notepad didn't open"
        apply(hwnd, Place((100, 100, 640, 480), (100, 100, 640, 480)))
        time.sleep(0.3)
        move(hwnd, 150, 120)
        time.sleep(0.3)
        assert read(hwnd).rect == (150, 120, 640, 480)
        text = describe(hwnd)
        assert "dpi" in text and "aware" in text, text
    finally:
        notepad.kill()

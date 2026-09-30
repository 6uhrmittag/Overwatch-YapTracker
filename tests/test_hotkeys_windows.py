"""RegisterHotKey for real. Windows only; CI runs this on the Windows runner.

The test presses the keys itself (keybd_event); the app never does.
"""

import ctypes
import sys
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="hotkeys need Windows")


def test_registered_hotkey_calls_back():
    from yaptracker.hotkeys import HotkeyListener

    pressed = threading.Event()
    listener = HotkeyListener({"Ctrl+Alt+F9": pressed.set})
    listener.start()
    try:
        assert listener.failed == []
        keybd = ctypes.windll.user32.keybd_event
        for vk in (0x11, 0x12, 0x78):  # Ctrl, Alt, F9 down
            keybd(vk, 0, 0, 0)
        for vk in (0x78, 0x12, 0x11):  # and up again
            keybd(vk, 0, 2, 0)
        assert pressed.wait(5), "hotkey was not delivered"
    finally:
        listener.stop()
        time.sleep(0.2)

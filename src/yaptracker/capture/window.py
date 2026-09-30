"""Find the Overwatch window the way OBS does: by its window class. Windows only.

No handle to the game process is ever opened (anti-cheat), and titles alone are unreliable:
a browser tab or folder called "Overwatch-YapTracker" must not match.
"""

import ctypes
from ctypes import wintypes

WINDOW_CLASS = "TankWindowClass"  # Overwatch's main window (OBS: "Overwatch:TankWindowClass")
WINDOW_TITLE = "Overwatch"


def find_overwatch() -> int | None:
    """HWND of the visible Overwatch window, or None while the game isn't running."""
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    hwnd = user32.FindWindowW(WINDOW_CLASS, None) or user32.FindWindowW(None, WINDOW_TITLE)
    return hwnd if hwnd and user32.IsWindowVisible(hwnd) else None

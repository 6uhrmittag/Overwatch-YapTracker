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


def has_title_bar(hwnd: int) -> bool:
    """Windowed mode (title bar and frame) rather than borderless or fullscreen (#76).

    Reads the window's style, like any window manager does; the game process isn't touched.
    """
    ws_caption = 0x00C00000
    user32 = ctypes.windll.user32
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    return user32.GetWindowLongW(hwnd, -16) & ws_caption == ws_caption  # GWL_STYLE

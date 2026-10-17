"""Is something on top of the chat box? (#497) Only matters where the chat box is read from the
screen (GDI: Windows 10, or a window capture that stays black, #236): there, File Explorer or a
tooltip over the box is in the picture and was read as chat ("gj E:\\data\\shots").

Window capture (WGC) never sees other windows, so it never asks. Reads window positions and
styles like any window manager; the game process isn't touched.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from yaptracker.capture.source import Region


@dataclass(frozen=True)
class TopWindow:
    """A top-level window above Overwatch, as Windows lists them."""

    rect: tuple[int, int, int, int]  # left, top, right, bottom on the screen
    visible: bool = True
    minimised: bool = False
    cloaked: bool = False  # hidden by the shell (other desktops, suspended apps)
    click_through: bool = False  # WS_EX_TRANSPARENT: overlays drawn over games (Discord, GPU)
    invisible: bool = False  # layered and (nearly) fully transparent
    overlay: bool = False  # layered and over the whole game window: a GPU/recording overlay
    hwnd: int = 0


def overlaps(rect: tuple[int, int, int, int], box: Region) -> bool:
    left, top, right, bottom = rect
    across = left < box.x + box.width and box.x < right
    return across and top < box.y + box.height and box.y < bottom


def hides(window: TopWindow, box: Region) -> bool:
    """Invisible, minimised, cloaked, click-through and overlay windows hide nothing."""
    gone = not window.visible or window.minimised or window.cloaked
    see_through = window.click_through or window.invisible or window.overlay
    return not (gone or see_through) and overlaps(window.rect, box)


def first_cover(above: Iterable[TopWindow], box: Region) -> TopWindow | None:
    """The first window above Overwatch that hides part of the box (screen pixels), or None."""
    return next((window for window in above if hides(window, box)), None)


def windows_above(hwnd: int, limit: int = 200):  # pragma: no cover - Windows only
    """The top-level windows above `hwnd` in the Z-order, nearest first, one at a time: the
    caller stops at the first that covers the box (cheap, it runs with every screen grab)."""
    import ctypes
    from ctypes import wintypes

    user32, dwmapi = ctypes.windll.user32, ctypes.windll.dwmapi
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    game = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(game))
    current = hwnd
    for _ in range(limit):
        current = user32.GetWindow(current, 3)  # GW_HWNDPREV: the window above
        if not current:
            return
        if not user32.IsWindowVisible(current) or user32.IsIconic(current):
            yield TopWindow((0, 0, 0, 0), visible=False, hwnd=current)
            continue
        rect = wintypes.RECT()
        if dwmapi.DwmGetWindowAttribute(current, 9, ctypes.byref(rect), ctypes.sizeof(rect)):
            user32.GetWindowRect(current, ctypes.byref(rect))  # 9: frame without the shadow
        cloaked = ctypes.c_int(0)
        dwmapi.DwmGetWindowAttribute(current, 14, ctypes.byref(cloaked), 4)  # DWMWA_CLOAKED
        style = user32.GetWindowLongW(current, -20)  # GWL_EXSTYLE
        layered = bool(style & 0x80000)
        alpha, flags = ctypes.c_ubyte(255), ctypes.c_uint(0)
        read = layered and user32.GetLayeredWindowAttributes(
            current, None, ctypes.byref(alpha), ctypes.byref(flags))  # fmt: skip
        invisible = bool(read) and bool(flags.value & 0x2) and alpha.value < 10  # LWA_ALPHA
        whole = (rect.left <= game.left and rect.top <= game.top and rect.right >= game.right
                 and rect.bottom >= game.bottom)  # fmt: skip
        yield TopWindow(
            (rect.left, rect.top, rect.right, rect.bottom),
            cloaked=bool(cloaked.value),
            click_through=bool(style & 0x20),
            invisible=invisible,
            overlay=layered and whole,
            hwnd=current,
        )


def title(hwnd: int) -> str:  # pragma: no cover - Windows only
    """A window's title, or its class when it has none."""
    import ctypes

    text = ctypes.create_unicode_buffer(256)
    if ctypes.windll.user32.GetWindowTextW(hwnd, text, 256):
        return text.value
    ctypes.windll.user32.GetClassNameW(hwnd, text, 256)
    return text.value


def covering(hwnd: int, box: Region) -> str | None:  # pragma: no cover - Windows only
    """What hides part of the chat box (screen pixels), by its title for Live; None if free."""
    window = first_cover(windows_above(hwnd), box)
    return title(window.hwnd) if window is not None else None

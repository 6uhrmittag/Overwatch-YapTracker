"""YapTracker opens where you left it (#253): same screen, place, size, maximised or snapped.

The window belongs to pywebview's child process, so it's found by title and exe like Ctrl+Alt+F
does (single_instance) and placed with Win32 calls on a thread in real pixels. The place lives
in config.json, so updates keep it. It's only restored while its title bar is still on a
connected screen; otherwise Windows' default place, so it never opens off-screen.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

log = logging.getLogger(__name__)
TITLE_BAR = 32  # px of the window's top that must stay reachable to drag it
SETTLE_S = 1.0  # saved once it stopped moving this long
POLL_S = 2.0

Rect = tuple[int, int, int, int]  # x, y, width, height in screen pixels


@dataclass(frozen=True)
class Place:
    rect: Rect  # where it is: a snapped window's half too
    normal: Rect  # where it goes when un-maximised
    maximized: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "Place | None":
        try:
            return cls(tuple(data["rect"]), tuple(data["normal"]), bool(data["maximized"]))
        except (KeyError, TypeError, ValueError):
            return None


def visible(place: Place, screens: list[Rect], share: float = 0.25) -> bool:
    """At least `share` of the title bar is on a connected screen (rects are whole monitors):
    a quarter of it is plenty to grab and drag."""
    x, y, width, _ = place.normal if place.maximized else place.rect
    if width <= 0:
        return False
    covered = 0
    for sx, sy, sw, sh in screens:
        left, right = max(x, sx), min(x + width, sx + sw)
        top, bottom = max(y, sy), min(y + TITLE_BAR, sy + sh)
        if right > left and bottom > top:
            covered += (right - left) * (bottom - top)
    return covered >= share * width * TITLE_BAR


class Keeper:
    """Reads the place every few seconds and saves it once it settled (debounced)."""

    def __init__(
        self,
        read: Callable[[], Place | None],
        save: Callable[[Place], None],
        saved: Place | None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._read, self._save, self._saved, self._clock = read, save, saved, clock
        self._seen: Place | None = None
        self._since = 0.0

    def check(self) -> None:
        place = self._read()  # None while minimised: that's not a place to come back to
        if place is None or place == self._saved:
            self._seen = None
            return
        now = self._clock()
        if place != self._seen:
            self._seen, self._since = place, now
        elif now - self._since >= SETTLE_S:
            self._save(place)
            self._saved, self._seen = place, None

    def forget(self) -> None:
        self._saved = self._seen = None


# Windows -----------------------------------------------------------------------------------

_SW_SHOWNORMAL, _SW_SHOWMINIMIZED, _SW_SHOWMAXIMIZED, _SW_SHOWMINNOACTIVE = 1, 2, 3, 7
_PER_MONITOR_AWARE_V2 = -4


def _win32():
    import ctypes
    from ctypes import wintypes

    class Placement(ctypes.Structure):
        _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT),
                    ("showCmd", wintypes.UINT), ("ptMinPosition", wintypes.POINT),
                    ("ptMaxPosition", wintypes.POINT),
                    ("rcNormalPosition", wintypes.RECT)]  # fmt: skip

    user32 = ctypes.windll.user32
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetThreadDpiAwarenessContext(_PER_MONITOR_AWARE_V2)  # real pixels on every screen
    return ctypes, wintypes, user32, Placement


def _rect(r) -> Rect:
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def read(hwnd: int) -> Place | None:
    """The window's place now; None while minimised or gone."""
    ctypes, wintypes, user32, Placement = _win32()
    placement = Placement(length=ctypes.sizeof(Placement))
    rect = wintypes.RECT()
    if not user32.GetWindowPlacement(hwnd, ctypes.byref(placement)):
        return None
    if placement.showCmd == _SW_SHOWMINIMIZED or user32.IsIconic(hwnd):
        return None
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return Place(_rect(rect), _rect(placement.rcNormalPosition),
                 placement.showCmd == _SW_SHOWMAXIMIZED)  # fmt: skip


def apply(hwnd: int, place: Place, minimized: bool = False) -> None:
    """Back where it was. Maximised comes back maximised; a snapped half at its rectangle."""
    ctypes, wintypes, user32, Placement = _win32()
    placement = Placement(length=ctypes.sizeof(Placement))
    user32.GetWindowPlacement(hwnd, ctypes.byref(placement))
    x, y, w, h = place.normal if place.maximized else place.rect
    placement.rcNormalPosition = wintypes.RECT(x, y, x + w, y + h)
    placement.showCmd = (_SW_SHOWMINNOACTIVE if minimized
                         else _SW_SHOWMAXIMIZED if place.maximized else _SW_SHOWNORMAL)  # fmt: skip
    user32.SetWindowPlacement(hwnd, ctypes.byref(placement))
    if not (minimized or place.maximized):  # the placement is in work-area units: exact rect
        user32.SetWindowPos(hwnd, None, x, y, w, h, 0x0004 | 0x0010)  # NOZORDER | NOACTIVATE


def screens() -> list[Rect]:
    """Every connected monitor, in screen pixels."""
    ctypes, wintypes, user32, _ = _win32()
    found: list[Rect] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)  # fmt: skip
    def visit(_monitor, _dc, rect, _data):
        found.append(_rect(rect.contents))
        return True

    user32.EnumDisplayMonitors(None, None, visit, 0)
    return found


def keep(find: Callable[[], int | None], minimized: bool, stop: threading.Event) -> None:
    """The app's window thread: restore the saved place once the window exists, then save
    changes. Stops with `stop`; any Windows hiccup only costs the place, never the app."""
    from yaptracker import config

    try:
        hwnd = None
        for _ in range(120):  # the window shows up a few seconds after the server
            hwnd = find()
            if hwnd or stop.wait(0.5):
                break
        if not hwnd:
            return
        saved = Place.from_dict(config.window_place() or {})
        if saved is not None and visible(saved, screens()):
            apply(hwnd, saved, minimized)
            log.info("window: back at %s%s", saved.rect, " (maximised)" if saved.maximized else "")
        elif saved is not None:
            log.info("window: saved place %s is off every screen, default place", saved.rect)
        keeper = Keeper(lambda: read(hwnd), lambda p: config.save_window_place(asdict(p)), saved)
        _kept.update(hwnd=hwnd, keeper=keeper)
        while not stop.wait(POLL_S):
            keeper.check()
    except Exception:
        log.exception("window: couldn't keep its place")


_kept: dict = {}  # the window and its keeper, once found


def reset() -> bool:
    """Settings' Reset window position: forget the saved place and put the window in the
    middle of the main screen at its size - rescues one stuck off-screen. True if moved."""
    from yaptracker import config

    config.save_window_place(None)
    hwnd, keeper = _kept.get("hwnd"), _kept.get("keeper")
    if keeper is not None:
        keeper.forget()
    place = read(hwnd) if hwnd else None
    main = next((s for s in screens() if s[:2] == (0, 0)), None) if hwnd else None
    if place is not None and main is not None:
        w, h = min(place.normal[2], main[2]), min(place.normal[3], main[3])
        x, y = main[0] + (main[2] - w) // 2, main[1] + (main[3] - h) // 2
        apply(hwnd, Place((x, y, w, h), (x, y, w, h)))
        log.info("window: reset to the middle of the main screen")
        return True
    return False

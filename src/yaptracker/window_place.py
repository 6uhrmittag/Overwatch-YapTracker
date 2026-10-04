"""YapTracker opens where you left it (#253): same screen, place, size, maximised or snapped.

The window belongs to pywebview's child process, so it's found by title and exe like Ctrl+Alt+F
does (single_instance) and placed with Win32 calls on a thread in real pixels. The place lives
in config.json, so updates keep it. It's only restored while its title bar is still on a
connected screen; otherwise Windows' default place, so it never opens off-screen.
"""

import contextlib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

log = logging.getLogger(__name__)
TITLE_BAR = 32  # px of the window's top that must stay reachable to drag it
SETTLE_S = 1.0  # saved once it stopped moving this long
POLL_S = 2.0
BORDER = 10  # px a window may stick out of the work area: Windows' invisible resize border
ARRIVE_S = 1.0  # after a move to a screen with other scaling, the window resizes itself (#299)

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


def clamp(rect: Rect, works: list[Rect]) -> Rect:
    """The rect fitted into the work area it's mostly on (#299): never wider or taller than it,
    the title bar always inside. Windows' invisible border (BORDER) may stick out, so a snapped
    half stays as it is. `works`: every monitor's work area."""
    if not works:
        return rect
    x, y, w, h = rect

    def overlap(area: Rect) -> int:
        ax, ay, aw, ah = area
        return max(0, min(x + w, ax + aw) - max(x, ax)) * max(0, min(y + h, ay + ah) - max(y, ay))

    def distance(area: Rect) -> float:
        ax, ay, aw, ah = area
        return abs(x + w / 2 - (ax + aw / 2)) + abs(y + h / 2 - (ay + ah / 2))

    wx, wy, ww, wh = max(works, key=lambda a: (overlap(a), -distance(a)))
    wx, wy, ww, wh = wx - BORDER, wy - BORDER, ww + 2 * BORDER, wh + 2 * BORDER
    w, h = min(w, ww), min(h, wh)
    return min(max(x, wx), wx + ww - w), min(max(y, wy), wy + wh - h), w, h


def fit(place: Place, works: list[Rect]) -> Place:
    """The whole place clamped (#299): where it is and where it goes when un-maximised."""
    return Place(clamp(place.rect, works), clamp(place.normal, works), place.maximized)


class Keeper:
    """Reads the place every few seconds and saves it once it settled (debounced). Never saves
    more than fits the screen it's on (`fit`, #299): a wrong size can't grow from start to start."""

    def __init__(
        self,
        read: Callable[[], Place | None],
        save: Callable[[Place], None],
        saved: Place | None,
        clock: Callable[[], float] = time.monotonic,
        fit: Callable[[Place], Place] = lambda place: place,
    ) -> None:
        self._read, self._save, self._saved, self._clock = read, save, saved, clock
        self._fit = fit
        self._seen: Place | None = None
        self._since = 0.0

    def check(self) -> None:
        place = self._read()  # None while minimised: that's not a place to come back to
        place = self._fit(place) if place is not None else None
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


@dataclass(frozen=True)
class Monitor:
    rect: Rect
    work: Rect  # without the taskbar
    dpi: int  # 96 = 100 % scaling


def monitors() -> list[Monitor]:
    """Every connected monitor with its work area and scaling, in screen pixels."""
    ctypes, wintypes, user32, _ = _win32()

    class Info(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]  # fmt: skip

    found: list[Monitor] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)  # fmt: skip
    def visit(monitor, _dc, _rect, _data):
        info = Info(cbSize=ctypes.sizeof(Info))
        user32.GetMonitorInfoW(monitor, ctypes.byref(info))
        dpi_x, dpi_y = wintypes.UINT(96), wintypes.UINT(96)
        with contextlib.suppress(AttributeError, OSError):  # before 8.1: no per-monitor DPI
            ctypes.windll.shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(dpi_x),
                                                  ctypes.byref(dpi_y))  # fmt: skip
        found.append(Monitor(_rect(info.rcMonitor), _rect(info.rcWork), int(dpi_x.value)))
        return True

    user32.EnumDisplayMonitors(None, None, visit, 0)
    return found


def screens() -> list[Rect]:
    """Every connected monitor, in screen pixels."""
    return [m.rect for m in monitors()]


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
        found = monitors()
        log.info("window: screens %s", "; ".join(  # so the next report explains itself (#299)
            f"{m.rect} work {m.work} at {round(100 * m.dpi / 96)} %" for m in found))  # fmt: skip
        works = [m.work for m in found]
        saved = Place.from_dict(config.window_place() or {})
        if saved is not None and visible(saved, [m.rect for m in found]):
            wanted = fit(saved, works)
            if wanted != saved:
                log.info("window: saved place %s doesn't fit its screen, now %s", saved.rect,
                         wanted.rect)  # fmt: skip
            restore(hwnd, wanted, minimized, stop)
            saved = wanted
        elif saved is not None:
            log.info("window: saved place %s is off every screen, default place", saved.rect)
        keeper = Keeper(lambda: read(hwnd), lambda p: config.save_window_place(asdict(p)), saved,
                        fit=lambda p: fit(p, works))  # fmt: skip
        _kept.update(hwnd=hwnd, keeper=keeper)
        while not stop.wait(POLL_S):
            keeper.check()
    except Exception:
        log.exception("window: couldn't keep its place")


_kept: dict = {}  # the window and its keeper, once found


def restore(hwnd: int, wanted: Place, minimized: bool, stop: threading.Event) -> None:
    """Back at the saved place, checked: moved to a screen with other scaling, the window
    resizes itself after our move (WM_DPICHANGED, #299). Then it's on the right screen, and a
    second move sticks."""
    apply(hwnd, wanted, minimized)
    if minimized or wanted.maximized:
        log.info("window: back at %s%s", wanted.rect, " (maximised)" if wanted.maximized else "")
        return
    stop.wait(ARRIVE_S)
    got = read(hwnd)
    if got is None or got.rect == wanted.rect:
        log.info("window: back at %s", wanted.rect)
        return
    apply(hwnd, wanted)
    stop.wait(ARRIVE_S / 2)
    again = read(hwnd)
    log.info("window: asked %s, got %s, after a second move %s", wanted.rect, got.rect,
             again.rect if again else None)  # fmt: skip


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

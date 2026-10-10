"""YapTracker opens where you left it (#253): same screen, place, size, maximised or snapped.

The window belongs to pywebview's child process, so it's found by title and exe like Ctrl+Alt+F
does (single_instance) and placed with Win32 calls on a thread in real pixels. The place lives
in config.json, so updates keep it. It's only restored while its title bar is still on a
connected screen; otherwise Windows' default place, so it never opens off-screen.
"""

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

log = logging.getLogger(__name__)
TITLE_BAR = 32  # px of the window's top that must stay reachable to drag it
SETTLE_S = 1.0  # saved once it stopped moving this long
POLL_S = 2.0
BORDER = 10  # px a window may stick out of the work area at 100 %: Windows' invisible border
ARRIVE_S = 1.0  # after a move to a screen with other scaling, the window resizes itself (#299)
LATE_S = 3.0  # read back once more: a late WM_DPICHANGED would show by then (#365)

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


def home(rect: Rect, areas: list[Rect]) -> int:
    """Index of the area the rect is mostly on, else the nearest one. `areas` must not be empty."""
    x, y, w, h = rect

    def overlap(area: Rect) -> int:
        ax, ay, aw, ah = area
        return max(0, min(x + w, ax + aw) - max(x, ax)) * max(0, min(y + h, ay + ah) - max(y, ay))

    def distance(area: Rect) -> float:
        ax, ay, aw, ah = area
        return abs(x + w / 2 - (ax + aw / 2)) + abs(y + h / 2 - (ay + ah / 2))

    return max(range(len(areas)), key=lambda i: (overlap(areas[i]), -distance(areas[i])))


def border(dpi: int) -> int:
    """Windows' invisible resize border grows with the screen's scaling: 7 px at 100 %, 11 at
    150 %, a maximised window's 8 and 12 (#365). BORDER is 100 %'s with room to spare."""
    return math.ceil(BORDER * max(dpi, 96) / 96)


def clamp(rect: Rect, works: list[Rect], dpis: list[int] | None = None) -> Rect:
    """The rect fitted into the work area it's mostly on (#299): never wider or taller than it,
    the title bar always inside. Windows' invisible border may stick out, so a snapped half
    stays as it is. `works`: every monitor's work area; `dpis`: their scaling (96 if unknown)."""
    if not works:
        return rect
    x, y, w, h = rect
    i = home(rect, works)
    edge = border(dpis[i] if dpis else 96)
    wx, wy, ww, wh = works[i]
    wx, wy, ww, wh = wx - edge, wy - edge, ww + 2 * edge, wh + 2 * edge
    w, h = min(w, ww), min(h, wh)
    return min(max(x, wx), wx + ww - w), min(max(y, wy), wy + wh - h), w, h


def fit(place: Place, works: list[Rect], dpis: list[int] | None = None) -> Place:
    """The whole place clamped (#299): where it is and where it goes when un-maximised."""
    return Place(clamp(place.rect, works, dpis), clamp(place.normal, works, dpis),
                 place.maximized)  # fmt: skip


def birth(saved: Place | None, found: list["Monitor"]) -> dict:
    """pywebview's x, y, width and height for the saved place (#365): the window is born on its
    own screen, so it never has to cross to a screen with other scaling, which left it too tall.
    pywebview multiplies them by the scaling of the screen it's created on: the main one."""
    if saved is None or not found or not visible(saved, [m.rect for m in found]):
        return {}
    wanted = fit(saved, [m.work for m in found], [m.dpi for m in found])
    x, y, w, h = wanted.normal if wanted.maximized else wanted.rect
    main = next((m for m in found if m.rect[:2] == (0, 0)), found[0])
    scale = main.dpi / 96
    return {"x": round(x / scale), "y": round(y / scale),
            "width": max(1, round(w / scale)), "height": max(1, round(h / scale))}  # fmt: skip


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


def move(hwnd: int, x: int, y: int) -> None:
    """Only the window's top-left: it keeps its size (SWP_NOSIZE)."""
    _, _, user32, _ = _win32()
    user32.SetWindowPos(hwnd, None, x, y, 0, 0, 0x0001 | 0x0004 | 0x0010)


_AWARENESS = {0: "DPI unaware", 1: "system DPI aware", 2: "per-monitor DPI aware"}


def _screen_dpi(hwnd: int) -> int | None:
    """The scaling of the screen the window is on, as a DPI; None if Windows won't say."""
    try:
        ctypes, wintypes, user32, _ = _win32()
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        shcore = ctypes.windll.shcore
        shcore.GetDpiForMonitor.argtypes = [wintypes.HMONITOR, ctypes.c_int,
                                            ctypes.POINTER(wintypes.UINT),
                                            ctypes.POINTER(wintypes.UINT)]  # fmt: skip
        dpi_x, dpi_y = wintypes.UINT(0), wintypes.UINT(0)
        shcore.GetDpiForMonitor(user32.MonitorFromWindow(hwnd, 2), 0, ctypes.byref(dpi_x),
                                ctypes.byref(dpi_y))  # fmt: skip  # 2: the nearest screen
        return int(dpi_x.value) or None
    except Exception:
        return None


def describe(hwnd: int) -> str:
    """Where the window is and how it scales (#365): its own DPI, its screen's DPI and how
    DPI aware its process is. A window that doesn't follow its screen's DPI is resized by
    Windows when it crosses screens."""
    try:
        ctypes, wintypes, user32, _ = _win32()
        user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        user32.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
        user32.GetWindowDpiAwarenessContext.argtypes = [wintypes.HWND]
        user32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.AreDpiAwarenessContextsEqual.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        context = user32.GetWindowDpiAwarenessContext(hwnd)
        awareness = _AWARENESS.get(user32.GetAwarenessFromDpiAwarenessContext(context), "?")
        if user32.AreDpiAwarenessContextsEqual(context, _PER_MONITOR_AWARE_V2):
            awareness = "per-monitor DPI aware v2"
        place = read(hwnd)
        return (
            f"at {place.rect if place else None}, window {user32.GetDpiForWindow(hwnd)} dpi,"
            f" its screen {_screen_dpi(hwnd)} dpi, {awareness}"
        )
    except Exception as error:  # a diagnosis never stops the restore
        return f"no DPI details ({error})"


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
    # Declared, or a 64-bit monitor handle overflows ctypes' default int and the callback
    # fails silently, which ends the enumeration with no monitors at all (#299, CI).
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(Info)]
    shcore = getattr(ctypes.windll, "shcore", None)
    if shcore is not None:
        shcore.GetDpiForMonitor.argtypes = [wintypes.HMONITOR, ctypes.c_int,
                                            ctypes.POINTER(wintypes.UINT),
                                            ctypes.POINTER(wintypes.UINT)]  # fmt: skip

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)  # fmt: skip
    def visit(monitor, _dc, rect, _data):
        whole = _rect(rect.contents)
        try:
            info = Info(cbSize=ctypes.sizeof(Info))
            work = _rect(info.rcWork) if user32.GetMonitorInfoW(monitor, ctypes.byref(info)) \
                else whole  # fmt: skip
            dpi_x, dpi_y = wintypes.UINT(96), wintypes.UINT(96)
            if shcore is not None:
                shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
            found.append(Monitor(whole, work, int(dpi_x.value) or 96))
        except Exception:  # never lose the monitor itself over its details
            log.warning("window: no details for screen %s", whole, exc_info=True)
            found.append(Monitor(whole, whole, 96))
        return True

    user32.EnumDisplayMonitors(None, None, visit, 0)
    return found


def screens() -> list[Rect]:
    """Every connected monitor, in screen pixels."""
    return [m.rect for m in monitors()]


def birth_args() -> dict:
    """`birth` on this PC, for pywebview's window before it opens; {} on any hiccup. On its own
    thread, so the caller's DPI awareness stays as it was."""
    from yaptracker import config

    args: dict = {}

    def work() -> None:
        try:
            args.update(birth(Place.from_dict(config.window_place() or {}), monitors()))
        except Exception:
            log.warning("window: no saved place to open at", exc_info=True)

    thread = threading.Thread(target=work, name="window birth", daemon=True)
    thread.start()
    thread.join(5)
    if args:
        log.info("window: opens at %s (main screen's units)", args)
    return dict(args)


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
        works, dpis = [m.work for m in found], [m.dpi for m in found]
        saved = Place.from_dict(config.window_place() or {})
        if saved is not None and visible(saved, [m.rect for m in found]):
            wanted = fit(saved, works, dpis)
            if wanted != saved:
                log.info("window: saved place %s (normal %s) doesn't fit its screen, now %s"
                         " (normal %s)", saved.rect, saved.normal, wanted.rect,
                         wanted.normal)  # fmt: skip
            restore(hwnd, wanted, minimized, stop, found)
            saved = wanted
        elif saved is not None:
            log.info("window: saved place %s is off every screen, default place", saved.rect)
        keeper = Keeper(lambda: read(hwnd), lambda p: config.save_window_place(asdict(p)), saved,
                        fit=lambda p: fit(p, works, dpis))  # fmt: skip
        _kept.update(hwnd=hwnd, keeper=keeper)
        while not stop.wait(POLL_S):
            keeper.check()
    except Exception:
        log.exception("window: couldn't keep its place")


_kept: dict = {}  # the window and its keeper, once found


def restore(hwnd: int, wanted: Place, minimized: bool, stop: threading.Event,
            found: list[Monitor] | None = None) -> None:  # fmt: skip
    """Back at the saved place, checked (#299). The window is born on its screen (`birth`,
    #365); if it isn't there anyway, it's moved there first and only sized once it took on that
    screen's scaling: sized while crossing to other scaling, it came back too tall."""
    log.info("window: found %s", describe(hwnd))
    if minimized or wanted.maximized:
        apply(hwnd, wanted, minimized)
        log.info("window: back at %s%s", wanted.rect, " (maximised)" if wanted.maximized else "")
        return
    target = found[home(wanted.rect, [m.rect for m in found])] if found else None
    if target is not None and _screen_dpi(hwnd) != target.dpi:
        move(hwnd, *wanted.rect[:2])
        for _ in range(10):  # its scaling follows within a moment
            if _screen_dpi(hwnd) == target.dpi or stop.wait(ARRIVE_S / 10):
                break
        log.info("window: moved to its screen first, now %s", describe(hwnd))
    apply(hwnd, wanted)
    stop.wait(ARRIVE_S)
    got = read(hwnd)
    if got is not None and got.rect != wanted.rect:
        apply(hwnd, wanted)
    stop.wait(LATE_S - ARRIVE_S)
    late = read(hwnd)
    if got is None or late is None or got.rect == late.rect == wanted.rect:
        log.info("window: back at %s", wanted.rect)
        return
    log.info("window: asked %s, got %s after %g s, %s after %g s; %s", wanted.rect, got.rect,
             ARRIVE_S, late.rect, LATE_S, describe(hwnd))  # fmt: skip
    if target is not None and late.rect[3] > target.work[3] + 2 * border(target.dpi):
        log.warning("window: still taller than its screen (%d of %d px): something in the window"
                    " keeps it that tall", late.rect[3], target.work[3])  # fmt: skip


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

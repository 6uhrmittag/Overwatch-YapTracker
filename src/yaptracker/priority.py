"""Stay out of the game's way (#187): YapTracker runs below normal priority, and its heavy part,
the chat reader's OCR, in Windows' efficiency mode (EcoQoS) at the lowest thread priority. So
when the game needs a core, Windows gives it to the game. Windows only; elsewhere these do
nothing.

Since #563 the OCR has a process of its own, and only that one (and the window's) is in
efficiency mode: the main process (capture, watchdog, match signals, the UI's server) needs
milliseconds, but on time. In efficiency mode it waited seconds for a core in a match, and so
did everything behind it. It stays below normal: the game still goes first."""

import contextlib
import ctypes
import logging
import sys
from collections.abc import Iterator
from ctypes import wintypes

log = logging.getLogger(__name__)

BELOW_NORMAL_PRIORITY_CLASS = 0x4000
NORMAL_PRIORITY_CLASS = 0x20
THREAD_PRIORITY_LOWEST = -2
THREAD_PRIORITY_NORMAL = 0
_PROCESS_POWER_THROTTLING = 4  # SetProcessInformation class
_THROTTLE_EXECUTION_SPEED = 0x1


class _PowerThrottling(ctypes.Structure):
    _fields_ = [("version", ctypes.c_ulong), ("control_mask", ctypes.c_ulong),
                ("state_mask", ctypes.c_ulong)]  # fmt: skip


def _kernel32():
    """kernel32 with the signatures declared: without them ctypes cuts the 64-bit pseudo-handle
    of GetCurrentProcess() to 32 bits, and every call fails quietly."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    for name in ("GetCurrentProcess", "GetCurrentThread"):
        getattr(kernel32, name).restype = wintypes.HANDLE
    kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.GetPriorityClass.argtypes = [wintypes.HANDLE]
    kernel32.GetPriorityClass.restype = wintypes.DWORD
    kernel32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                               wintypes.DWORD]  # fmt: skip
    kernel32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
    kernel32.GetThreadPriority.argtypes = [wintypes.HANDLE]
    return kernel32


def lower_process(efficiency: bool = True) -> None:
    """Below-normal priority for this process; efficiency mode on, or switched off by name (not
    left to Windows, which puts processes without a visible window into it on its own)."""
    if sys.platform != "win32":
        return
    kernel32 = _kernel32()
    me = kernel32.GetCurrentProcess()
    lowered = bool(kernel32.SetPriorityClass(me, BELOW_NORMAL_PRIORITY_CLASS))
    if not lowered:
        log.warning("couldn't lower the process priority")
    state = _PowerThrottling(1, _THROTTLE_EXECUTION_SPEED,
                             _THROTTLE_EXECUTION_SPEED if efficiency else 0)  # fmt: skip
    if not kernel32.SetProcessInformation(me, _PROCESS_POWER_THROTTLING, ctypes.byref(state),
                                          ctypes.sizeof(state)):  # fmt: skip
        log.info("efficiency mode not available on this Windows")  # Windows 10 before 1709
    else:
        log.info("priority: %s, efficiency mode %s", "below normal" if lowered else "unchanged",
                 "on" if efficiency else "off")  # fmt: skip


def efficiency_mode() -> bool | None:
    """Whether this process is in efficiency mode by its own setting; None: Windows won't say."""
    if sys.platform != "win32":
        return None
    kernel32 = _kernel32()
    state = _PowerThrottling(1, 0, 0)
    kernel32.GetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                               wintypes.DWORD]  # fmt: skip
    if not kernel32.GetProcessInformation(kernel32.GetCurrentProcess(), _PROCESS_POWER_THROTTLING,
                                          ctypes.byref(state), ctypes.sizeof(state)):  # fmt: skip
        return None
    if not state.control_mask & _THROTTLE_EXECUTION_SPEED:
        return None  # nobody set it: Windows decides
    return bool(state.state_mask & _THROTTLE_EXECUTION_SPEED)


@contextlib.contextmanager
def lowest_for_now() -> Iterator[None]:
    """The calling thread at the lowest priority for one piece of heavy work, then back: OCR the
    main process has to do itself when the reader's own process can't (#563)."""
    if sys.platform != "win32":
        yield
        return
    kernel32 = _kernel32()
    thread = kernel32.GetCurrentThread()
    before = kernel32.GetThreadPriority(thread)
    kernel32.SetThreadPriority(thread, THREAD_PRIORITY_LOWEST)
    try:
        yield
    finally:
        if before != 0x7FFFFFFF:  # THREAD_PRIORITY_ERROR_RETURN: unknown, leave it
            kernel32.SetThreadPriority(thread, before)


def lower_this_thread() -> None:
    """The calling thread at the lowest priority: for the chat reader's OCR."""
    if sys.platform != "win32":
        return
    kernel32 = _kernel32()
    if not kernel32.SetThreadPriority(kernel32.GetCurrentThread(), THREAD_PRIORITY_LOWEST):
        log.warning("couldn't lower the chat reader's priority")


def brakes(on: bool) -> None:
    """The OCR child's brakes (#652). On: below normal, efficiency mode, its reading thread at
    the lowest priority (#187). Off, for "as fast as it can" (complete chat beats FPS): normal
    priority, efficiency mode off by name, the thread at normal priority."""
    if on:
        lower_process()
        lower_this_thread()
        return
    if sys.platform != "win32":
        return
    kernel32 = _kernel32()
    me = kernel32.GetCurrentProcess()
    normal = bool(kernel32.SetPriorityClass(me, NORMAL_PRIORITY_CLASS))
    state = _PowerThrottling(1, _THROTTLE_EXECUTION_SPEED, 0)
    eco_off = bool(
        kernel32.SetProcessInformation(
            me, _PROCESS_POWER_THROTTLING, ctypes.byref(state), ctypes.sizeof(state)
        )
    )
    thread = bool(kernel32.SetThreadPriority(kernel32.GetCurrentThread(), THREAD_PRIORITY_NORMAL))
    log.info("priority: no brakes (as fast as it can): %s priority, efficiency mode %s",
             "normal" if normal and thread else "couldn't set normal",
             "off" if eco_off else "unchanged (Windows refused)")  # fmt: skip


_main_braked: bool | None = None  # the main process's class as last set by main_brakes


def main_brakes(on: bool) -> None:
    """The main process's class (#652). On: below normal, the game first (#187). Off, for "as
    fast as it can": normal. Tonight's log (2026-11-26) had 23 capture gaps in matches (222 s
    of 45 min) where the capture thread got no core while the watchdog ticked on time. Its
    efficiency mode stays as __main__ set it. Said in the log when it changes."""
    global _main_braked
    if sys.platform != "win32" or on == _main_braked:
        return
    kernel32 = _kernel32()
    set_ = kernel32.SetPriorityClass(
        kernel32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS if on else NORMAL_PRIORITY_CLASS
    )
    if not set_:
        log.warning("couldn't set the app's priority to %s", "below normal" if on else "normal")
        return
    _main_braked = on
    log.info("priority: app %s", "below normal (brakes on)" if on else
             "at normal priority (no brakes: as fast as it can)")  # fmt: skip

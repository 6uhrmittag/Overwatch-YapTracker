"""Stay out of the game's way (#187): YapTracker runs below normal priority and in Windows'
efficiency mode (EcoQoS), the chat reader at the lowest thread priority. So when the game needs
a core, Windows gives it to the game. Windows only; elsewhere these do nothing."""

import ctypes
import logging
import sys
from ctypes import wintypes

log = logging.getLogger(__name__)

BELOW_NORMAL_PRIORITY_CLASS = 0x4000
THREAD_PRIORITY_LOWEST = -2
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


def lower_process() -> None:
    """Below-normal priority and EcoQoS for this process (the window's child process too)."""
    if sys.platform != "win32":
        return
    kernel32 = _kernel32()
    me = kernel32.GetCurrentProcess()
    if not kernel32.SetPriorityClass(me, BELOW_NORMAL_PRIORITY_CLASS):
        log.warning("couldn't lower the process priority")
    state = _PowerThrottling(1, _THROTTLE_EXECUTION_SPEED, _THROTTLE_EXECUTION_SPEED)
    if not kernel32.SetProcessInformation(me, _PROCESS_POWER_THROTTLING, ctypes.byref(state),
                                          ctypes.sizeof(state)):  # fmt: skip
        log.info("efficiency mode not available on this Windows")  # Windows 10 before 1709


def lower_this_thread() -> None:
    """The calling thread at the lowest priority: for the chat reader's OCR."""
    if sys.platform != "win32":
        return
    kernel32 = _kernel32()
    if not kernel32.SetThreadPriority(kernel32.GetCurrentThread(), THREAD_PRIORITY_LOWEST):
        log.warning("couldn't lower the chat reader's priority")

"""Only one YapTracker (#45): a second start brings the running one to the front. Windows only."""

import ctypes
import os
import sys
from ctypes import wintypes

MUTEX = "Local\\YapTracker"
_ERROR_ALREADY_EXISTS = 183
_SW_RESTORE = 9
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_held: list[int] = []  # the mutex lives as long as this process


def acquire(name: str = MUTEX) -> bool:
    """True if this is the only instance; the mutex is released when the process ends."""
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, name)
    already = kernel32.GetLastError() == _ERROR_ALREADY_EXISTS
    _held.append(handle)
    return not already


def _exe_of(pid: int) -> str | None:
    """Image name of one of *our* processes (never used on the game)."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        buf, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        return os.path.basename(buf.value).lower() if ok else None
    finally:
        kernel32.CloseHandle(handle)


def bring_running_to_front() -> bool:
    """Restore and focus the other YapTracker's window: title "YapTracker…" and our exe name.

    Checking the exe keeps an Explorer window of the folder "YapTracker" from matching.
    """
    user32 = ctypes.windll.user32
    me, exe = os.getpid(), os.path.basename(sys.executable).lower()
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if (
                title.value.startswith("YapTracker")
                and pid.value != me
                and _exe_of(pid.value) == exe
            ):
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(visit, 0)
    if found:
        user32.ShowWindow(found[0], _SW_RESTORE)
        user32.SetForegroundWindow(found[0])
    return bool(found)

"""What PC is this? (#214) So performance numbers from different PCs can be compared: version,
Windows, CPU, RAM, graphics cards, the display Overwatch runs on and the settings that change
the cost. In the log at every start (the display once Overwatch is found, the settings again
when they change), and in Settings -> About with a Copy button.

Local-only: no hostname, no user name, no serials; nothing leaves the PC unless it's copied.
Read from Windows (registry, DXGI, the display settings); the game process is never touched.
"""

import ctypes
import logging
import os
import platform
import sys
import threading
from dataclasses import dataclass

from yaptracker import __version__, config, gpu
from yaptracker.ocr import engine as ocr

log = logging.getLogger(__name__)
_lock = threading.Lock()
_machine: list[str] | None = None
_game: str | None = None
_settings: str | None = None


@dataclass(frozen=True)
class Display:
    width: int
    height: int
    hz: int
    hdr: bool | None  # None: Windows didn't say


def windows() -> str:
    """'Windows 11 Pro 24H2 (build 26100.4061)'."""
    if sys.platform != "win32":
        return f"{platform.system()} {platform.release()} (not Windows)"
    import winreg

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                        r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as key:  # fmt: skip

        def value(name: str, default=""):
            try:
                return winreg.QueryValueEx(key, name)[0]
            except OSError:
                return default

        name, build = value("ProductName", "Windows"), value("CurrentBuildNumber", "?")
        version, ubr = value("DisplayVersion"), value("UBR", None)
    if build.isdigit() and int(build) >= 22000:  # Windows 11 still calls itself 10 here
        name = name.replace("Windows 10", "Windows 11")
    full = f"{build}.{ubr}" if ubr is not None else build
    return " ".join(part for part in (name, version, f"(build {full})") if part)


def _physical_cores() -> int | None:
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    function = kernel32.GetLogicalProcessorInformationEx
    function.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    size = wintypes.DWORD(0)
    kernel32.GetLogicalProcessorInformationEx(0, None, ctypes.byref(size))  # RelationProcessorCore
    buffer = ctypes.create_string_buffer(size.value)
    if not kernel32.GetLogicalProcessorInformationEx(0, buffer, ctypes.byref(size)):
        return None
    cores, offset = 0, 0
    while offset < size.value:  # records of varying size: Relationship, Size, ...
        cores += 1
        offset += int.from_bytes(buffer.raw[offset + 4 : offset + 8], "little")
    return cores


def cpu() -> str:
    """'AMD Ryzen 9 7950X3D, 16 cores / 32 threads'."""
    threads = os.cpu_count() or 0
    if sys.platform != "win32":
        return f"{platform.processor() or platform.machine()}, {threads} threads"
    import winreg

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                        r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:  # fmt: skip
        name = " ".join(str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).split())
    cores = _physical_cores()
    return f"{name}, {cores} cores / {threads} threads" if cores else f"{name}, {threads} threads"


def ram() -> str:
    """Installed memory, '64 GB'."""
    if sys.platform != "win32":
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        return f"{total / 1024**3:.0f} GB"
    kb = ctypes.c_ulonglong(0)
    ctypes.windll.kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(kb))
    return f"{kb.value / 1024**2:.0f} GB"


def gpus() -> str:
    """'GPU 0 NVIDIA GeForce RTX 4090 (24 GB) | GPU 1 AMD Radeon(TM) Graphics (iGPU)'."""
    cards, seen = [], set()
    for a in gpu.adapters():
        if (a.name, a.dedicated) in seen:
            continue  # one card can be listed twice (seen with virtual-monitor drivers)
        seen.add((a.name, a.dedicated))
        memory = f"{a.dedicated / 1024**3:.0f} GB" if a.dedicated >= gpu.MIN_DEDICATED else "iGPU"
        cards.append(f"GPU {a.index} {a.name} ({memory})")
    return " | ".join(cards) or "GPU: none found"


def display_of(hwnd: int) -> Display | None:
    """Resolution, refresh rate and HDR of the monitor the window is on (Windows only)."""
    from ctypes import wintypes

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                    ("szDevice", ctypes.c_wchar * 32)]  # fmt: skip

    class DEVMODEW(ctypes.Structure):
        W, D = wintypes.WORD, wintypes.DWORD
        _fields_ = [("dmDeviceName", ctypes.c_wchar * 32), ("dmSpecVersion", W),
                    ("dmDriverVersion", W), ("dmSize", W), ("dmDriverExtra", W), ("dmFields", D),
                    ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG),
                    ("dmDisplayOrientation", D), ("dmDisplayFixedOutput", D),
                    ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
                    ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short),
                    ("dmCollate", ctypes.c_short), ("dmFormName", ctypes.c_wchar * 32),
                    ("dmLogPixels", W), ("dmBitsPerPel", D), ("dmPelsWidth", D),
                    ("dmPelsHeight", D), ("dmDisplayFlags", D), ("dmDisplayFrequency", D),
                    ("dmICMMethod", D), ("dmICMIntent", D), ("dmMediaType", D),
                    ("dmDitherType", D), ("dmReserved1", D), ("dmReserved2", D),
                    ("dmPanningWidth", D), ("dmPanningHeight", D)]  # fmt: skip

    user32 = ctypes.windll.user32
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
    user32.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                            ctypes.POINTER(DEVMODEW)]  # fmt: skip
    monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    info = MONITORINFOEXW(cbSize=ctypes.sizeof(MONITORINFOEXW))
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    mode = DEVMODEW(dmSize=ctypes.sizeof(DEVMODEW))
    if not user32.EnumDisplaySettingsW(info.szDevice, 0xFFFFFFFF, ctypes.byref(mode)):  # CURRENT
        return None
    return Display(mode.dmPelsWidth, mode.dmPelsHeight, mode.dmDisplayFrequency,
                   _hdr(info.szDevice))  # fmt: skip


def _hdr(device: str) -> bool | None:
    """Windows HDR on that monitor: DXGI says colour space G2084/P2020 (as in #174)."""
    from ctypes import wintypes

    class DESC1(ctypes.Structure):
        _fields_ = [("DeviceName", ctypes.c_wchar * 32), ("Desktop", wintypes.RECT),
                    ("Attached", wintypes.BOOL), ("Rotation", ctypes.c_int),
                    ("Monitor", wintypes.HMONITOR), ("BitsPerColor", ctypes.c_uint),
                    ("ColorSpace", ctypes.c_int), ("Primaries", ctypes.c_float * 8),
                    ("MinLum", ctypes.c_float), ("MaxLum", ctypes.c_float),
                    ("MaxFullFrameLum", ctypes.c_float)]  # fmt: skip

    def method(obj, index, *argtypes):
        vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtbl[index])

    def iid(text: str):
        import uuid

        return (ctypes.c_ubyte * 16)(*uuid.UUID(text).bytes_le)

    factory = ctypes.c_void_p()
    if ctypes.windll.dxgi.CreateDXGIFactory1(
        iid("770aae78-f26f-4dba-a829-253c83d1b387"), ctypes.byref(factory)
    ):
        return None
    output6_iid = iid("068346e8-aaec-4b84-add7-137f513f77a1")
    for a in range(16):
        adapter = ctypes.c_void_p()
        try:  # IDXGIFactory1::EnumAdapters1
            method(factory, 12, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(
                factory, a, ctypes.byref(adapter)
            )
        except OSError:
            return None
        for o in range(16):
            output, output6 = ctypes.c_void_p(), ctypes.c_void_p()
            try:  # IDXGIAdapter::EnumOutputs, QueryInterface(IDXGIOutput6), GetDesc1
                method(adapter, 7, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(
                    adapter, o, ctypes.byref(output)
                )
                method(output, 0, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
                    output, ctypes.addressof(output6_iid), ctypes.byref(output6)
                )
                desc = DESC1()
                method(output6, 27, ctypes.POINTER(DESC1))(output6, ctypes.byref(desc))
            except OSError:
                break
            if desc.DeviceName == device:
                return desc.ColorSpace == 12  # DXGI_COLOR_SPACE_RGB_FULL_G2084_NONE_P2020
    return None


def machine() -> list[str]:
    """The lines about this PC; collected once (DXGI and the registry take a few ms)."""
    global _machine
    with _lock:
        if _machine is None:
            _machine = [
                f"YapTracker v{__version__} | {windows()}",
                f"CPU {cpu()} | RAM {ram()}",
                gpus(),
            ]
        return list(_machine)


def game_line(display: Display | None, width: int, height: int, mode: str) -> str:
    window = f"Overwatch window {width}x{height} {mode}"
    if display is None:
        return f"display of Overwatch: unknown | {window}"
    hdr = {True: "HDR on", False: "HDR off", None: "HDR unknown"}[display.hdr]
    return (f"display of Overwatch: {display.width}x{display.height} @ {display.hz} Hz, {hdr} "
            f"| {window}")  # fmt: skip


def settings_line() -> str:
    engine = ocr.LABELS.get(config.ocr_engine(), config.ocr_engine())
    on = {True: "on", False: "off"}
    return (f"settings: OCR {engine}, GPU OCR {on[config.ocr_gpu()]}, read every "
            f"{config.read_every_s():g} s, debug samples {on[config.debug_samples()]}")  # fmt: skip


def log_at_start() -> None:
    for line in machine():
        log.info("system: %s", line)
    log_settings()


def log_settings() -> None:
    """The settings line, whenever it differs from the last one logged."""
    global _settings
    line = settings_line()
    with _lock:
        if line == _settings:
            return
        _settings = line
    log.info("system: %s", line)


def game_found(hwnd: int | None, width: int, height: int) -> None:
    """Once Overwatch's first frame arrives: the display it's on and its window."""
    global _game
    display, mode = None, "borderless"
    if hwnd and sys.platform == "win32":
        from yaptracker.capture.window import has_title_bar

        try:
            display = display_of(hwnd)
        except OSError as error:
            log.warning("system: display unknown (%s)", error)
        mode = "windowed" if has_title_bar(hwnd) else "borderless"
    line = game_line(display, width, height, mode)
    with _lock:
        if line == _game:
            return
        _game = line
    log.info("system: %s", line)


def summary() -> list[str]:
    """For Settings -> About and Copy system info."""
    with _lock:
        game = _game or "display of Overwatch: not found yet"
    return [*machine(), game, settings_line()]

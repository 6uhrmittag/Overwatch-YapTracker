"""Which graphics card may OCR use? (#208) The dedicated one: the hardware adapter with the most
video memory of its own. Integrated GPUs share system memory and were no help (#126); software
adapters are skipped. Windows only (DXGI); elsewhere there is none.

DirectML's device_id is the adapter's index in this same DXGI order.
"""

import ctypes
import sys
from dataclasses import dataclass

MIN_DEDICATED = 2 * 1024**3  # an iGPU reserves a few hundred MB; a gaming card has gigabytes
_SOFTWARE = 2  # DXGI_ADAPTER_FLAG_SOFTWARE


@dataclass(frozen=True)
class Adapter:
    index: int
    name: str
    dedicated: int  # bytes of video memory of its own


def _desc1_type():
    from ctypes import wintypes

    class LUID(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.LONG)]

    class DESC1(ctypes.Structure):
        _fields_ = [("Description", ctypes.c_wchar * 128), ("VendorId", ctypes.c_uint),
                    ("DeviceId", ctypes.c_uint), ("SubSysId", ctypes.c_uint),
                    ("Revision", ctypes.c_uint), ("DedicatedVideoMemory", ctypes.c_size_t),
                    ("DedicatedSystemMemory", ctypes.c_size_t),
                    ("SharedSystemMemory", ctypes.c_size_t), ("AdapterLuid", LUID),
                    ("Flags", ctypes.c_uint)]  # fmt: skip

    return DESC1


def adapters() -> list[Adapter]:
    """Every hardware graphics adapter, in DXGI order."""
    if sys.platform != "win32":
        return []
    import uuid

    def method(obj, index, *argtypes):
        vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtbl[index])

    iid = (ctypes.c_ubyte * 16)(*uuid.UUID("770aae78-f26f-4dba-a829-253c83d1b387").bytes_le)
    factory = ctypes.c_void_p()
    if ctypes.windll.dxgi.CreateDXGIFactory1(iid, ctypes.byref(factory)) != 0:
        return []
    desc_type, found, index = _desc1_type(), [], 0
    while True:
        adapter = ctypes.c_void_p()
        try:  # IDXGIFactory1::EnumAdapters1
            method(factory, 12, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(
                factory, index, ctypes.byref(adapter)
            )
        except OSError:  # DXGI_ERROR_NOT_FOUND: no more adapters
            break
        desc = desc_type()
        method(adapter, 10, ctypes.POINTER(desc_type))(adapter, ctypes.byref(desc))  # GetDesc1
        if not desc.Flags & _SOFTWARE:
            found.append(Adapter(index, desc.Description, desc.DedicatedVideoMemory))
        index += 1
    return found


def dedicated() -> Adapter | None:
    """The graphics card OCR may use, or None (only an iGPU, or not Windows)."""
    cards = [a for a in adapters() if a.dedicated >= MIN_DEDICATED]
    return max(cards, key=lambda a: a.dedicated, default=None)

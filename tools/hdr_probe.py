"""Which monitors run with Windows HDR on? (spike #174)

    python tools/hdr_probe.py        (on Windows)

Asks DXGI (IDXGIOutput6::GetDesc1) for each monitor's colour space: G2084/P2020 means HDR.
Read-only, touches no game. Desktop sizes are DPI-scaled unless the process is DPI-aware.
"""

import ctypes
import time
from ctypes import wintypes


class GUID(ctypes.Structure):
    _fields_ = [
        ("a", ctypes.c_uint32),
        ("b", ctypes.c_uint16),
        ("c", ctypes.c_uint16),
        ("d", ctypes.c_ubyte * 8),
    ]


def guid(s):
    import uuid

    u = uuid.UUID(s)
    g = GUID(u.time_low, u.time_mid, u.time_hi_version)
    g.d[:] = list(u.bytes[8:])
    return g


class DESC1(ctypes.Structure):
    _fields_ = [
        ("DeviceName", ctypes.c_wchar * 32),
        ("Desktop", wintypes.RECT),
        ("Attached", wintypes.BOOL),
        ("Rotation", ctypes.c_int),
        ("Monitor", wintypes.HMONITOR),
        ("BitsPerColor", ctypes.c_uint),
        ("ColorSpace", ctypes.c_int),
        ("Primaries", ctypes.c_float * 8),
        ("MinLum", ctypes.c_float),
        ("MaxLum", ctypes.c_float),
        ("MaxFullFrameLum", ctypes.c_float),
    ]


def method(obj, index, *argtypes):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtbl[index])


started = time.perf_counter()
factory = ctypes.c_void_p()
ctypes.windll.dxgi.CreateDXGIFactory1(
    ctypes.byref(guid("770aae78-f26f-4dba-a829-253c83d1b387")), ctypes.byref(factory)
)
out6_iid = guid("068346e8-aaec-4b84-add7-137f513f77a1")
a = 0
while True:
    adapter = ctypes.c_void_p()
    try:
        method(factory, 12, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(
            factory, a, ctypes.byref(adapter)
        )
    except OSError:
        break
    o = 0
    while True:
        output = ctypes.c_void_p()
        try:
            method(adapter, 7, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(
                adapter, o, ctypes.byref(output)
            )
        except OSError:
            break
        out6 = ctypes.c_void_p()
        method(output, 0, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(
            output, ctypes.byref(out6_iid), ctypes.byref(out6)
        )
        d = DESC1()
        method(out6, 27, ctypes.POINTER(DESC1))(out6, ctypes.byref(d))
        r = d.Desktop
        hdr = d.ColorSpace == 12  # DXGI_COLOR_SPACE_RGB_FULL_G2084_NONE_P2020
        print(
            f"adapter {a} output {o}: {d.DeviceName} {r.right - r.left}x{r.bottom - r.top} "
            f"at {r.left},{r.top} bits={d.BitsPerColor} colorspace={d.ColorSpace} HDR={hdr} "
            f"maxlum={d.MaxLum:.0f}"
        )
        o += 1
    a += 1
print(f"{(time.perf_counter() - started) * 1000:.1f} ms")

"""When did Overwatch start? (#99) Windows only.

Read from the system's process list, the same snapshot Task Manager shows. No handle to the
game process is opened (anti-cheat): OpenProcess, psutil and friends are off limits.
"""

import ctypes
import struct

_SYSTEM_PROCESS_INFORMATION = 5
_STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
# SYSTEM_PROCESS_INFORMATION on 64-bit Windows: offsets of the fields we read.
_CREATE_TIME = 32  # 100 ns ticks since 1601
_IMAGE_NAME = 56  # UNICODE_STRING: length (bytes), max length, pointer to the characters
_EPOCH_AS_FILETIME = 116_444_736_000_000_000


def started_at(image: str = "Overwatch.exe") -> float | None:
    """Unix time the newest process called `image` started, or None if none runs."""
    ntdll = ctypes.windll.ntdll
    size = 1 << 20
    while True:
        buffer = ctypes.create_string_buffer(size)
        needed = ctypes.c_ulong()
        status = ntdll.NtQuerySystemInformation(
            _SYSTEM_PROCESS_INFORMATION, buffer, size, ctypes.byref(needed)
        )
        if status & 0xFFFFFFFF != _STATUS_INFO_LENGTH_MISMATCH:
            break
        size = max(size * 2, needed.value + 65536)  # processes come and go between calls
    if status != 0:
        return None
    base, offset, newest = ctypes.addressof(buffer), 0, None
    while True:
        (next_offset,) = struct.unpack_from("<I", buffer, offset)
        (created,) = struct.unpack_from("<q", buffer, offset + _CREATE_TIME)
        length, _, pointer = struct.unpack_from("<HH4xQ", buffer, offset + _IMAGE_NAME)
        if pointer and base <= pointer < base + size:
            name = ctypes.wstring_at(pointer, length // 2)
            if name.lower() == image.lower() and created:
                ts = (created - _EPOCH_AS_FILETIME) / 10_000_000
                newest = ts if newest is None else max(newest, ts)
        if not next_offset:
            return newest
        offset += next_offset

"""System info (#214) from the real Windows APIs. Windows only; CI runs it on the Windows runner."""

import ctypes
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="registry, DXGI and user32")


def test_windows_cpu_ram_and_cards():
    from yaptracker import system_info

    assert system_info.windows().startswith("Windows ") and "(build " in system_info.windows()
    assert " cores / " in system_info.cpu() and system_info.cpu().endswith(" threads")
    assert system_info.ram().endswith(" GB") and int(system_info.ram().split()[0]) > 0
    assert system_info.gpus()  # the runner may have no hardware card: "GPU: none found"


def test_the_display_a_window_is_on():
    from yaptracker import system_info

    display = system_info.display_of(ctypes.windll.user32.GetDesktopWindow())
    assert display is not None and display.width > 0 and display.height > 0
    assert display.hdr in (True, False, None)

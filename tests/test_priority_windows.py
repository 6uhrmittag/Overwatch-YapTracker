"""YapTracker gives way to the game (#187). Windows only; CI runs this on the Windows runner."""

import ctypes
import sys
import threading

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="process priority is Windows")


def test_process_below_normal_and_reader_thread_lowest():
    from yaptracker import priority

    kernel32 = ctypes.windll.kernel32
    priority.lower_process()
    assert kernel32.GetPriorityClass(kernel32.GetCurrentProcess()) == 0x4000  # BELOW_NORMAL
    seen = []

    def reader():
        priority.lower_this_thread()
        seen.append(kernel32.GetThreadPriority(kernel32.GetCurrentThread()))

    thread = threading.Thread(target=reader)
    thread.start()
    thread.join()
    assert seen == [-2]  # THREAD_PRIORITY_LOWEST

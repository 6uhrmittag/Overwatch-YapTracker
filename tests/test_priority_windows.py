"""YapTracker gives way to the game (#187). Windows only; CI runs this on the Windows runner."""

import sys
import threading

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="process priority is Windows")


def test_process_below_normal_and_reader_thread_lowest():
    from yaptracker import priority

    kernel32 = priority._kernel32()
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


def test_efficiency_mode_can_be_switched_off_by_name_and_on_again():
    """#563: the main process leaves efficiency mode, the reader's process keeps it."""
    from yaptracker import priority

    kernel32 = priority._kernel32()
    try:
        priority.lower_process(efficiency=False)
        assert kernel32.GetPriorityClass(kernel32.GetCurrentProcess()) == 0x4000  # still below
        assert priority.efficiency_mode() in (False, None)  # None: this Windows won't say
        priority.lower_process()
        assert priority.efficiency_mode() in (True, None)
    finally:
        priority.lower_process()

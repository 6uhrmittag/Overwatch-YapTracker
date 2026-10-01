"""The game's start time from the process list, no handle opened (#99). Windows only."""

import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows process list")


def test_start_time_of_a_running_process():
    from yaptracker.capture.process import started_at

    started = started_at(Path(sys.executable).name)  # this test's own python.exe
    assert started is not None and time.time() - 3600 < started <= time.time()


def test_no_such_process_means_no_start_time():
    from yaptracker.capture.process import started_at

    assert started_at("NoSuchGame-YapTracker.exe") is None

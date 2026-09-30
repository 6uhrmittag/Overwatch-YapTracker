"""Real HKCU Run key and a real named mutex. Windows only; CI runs this on the Windows runner."""

import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows registry and mutexes")


def test_run_entry_roundtrip():
    from yaptracker import autostart

    name = "YapTrackerTest"
    try:
        autostart.write('"C:\\x\\YapTracker.exe" --background', name)
        assert autostart.read(name) == '"C:\\x\\YapTracker.exe" --background'
    finally:
        autostart.write(None, name)
    assert autostart.read(name) is None
    autostart.write(None, name)  # removing twice is fine


def test_second_instance_is_refused_while_the_first_runs():
    from yaptracker import single_instance

    name = "Local\\YapTrackerTest"
    assert single_instance.acquire(name)
    code = f"from yaptracker import single_instance; print(single_instance.acquire({name!r}))"
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"

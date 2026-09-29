import re
import subprocess
import sys

from yaptracker import __version__


def test_version_is_pep440_like():
    assert re.fullmatch(r"\d+\.\d+\.\d+(\.dev\d+)?", __version__)


def test_module_prints_version():
    result = subprocess.run(
        [sys.executable, "-m", "yaptracker", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == f"YapTracker {__version__}"

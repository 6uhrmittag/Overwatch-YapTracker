"""Update now's PowerShell (#46) with a stand-in update.ps1. Windows only; CI runs it."""

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from yaptracker.updates import update_command

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="PowerShell runs on Windows")


def fake_install(tmp_path: Path, script: str) -> tuple[Path, Path]:
    """<root>\\app\\YapTracker.exe (whoami: starts, exits) and an update.ps1 stand-in, in a
    folder with an apostrophe like C:\\Users\\O'Brien."""
    root = tmp_path / "O'Brien" / "YapTracker"
    (root / "app").mkdir(parents=True)
    shutil.copy(Path(r"C:\Windows\System32\whoami.exe"), root / "app" / "YapTracker.exe")
    update = tmp_path / "YapTracker-update.ps1"
    update.write_text(script, encoding="ascii")
    return root, update


def test_the_update_runs_with_the_install_root(tmp_path):
    root, update = fake_install(
        tmp_path, "param($InstallRoot)\nSet-Content \"$InstallRoot\\ran.txt\" 'ok'\n"
    )
    done = subprocess.run(update_command(update, root), capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert (root / "ran.txt").read_text().strip() == "ok"


def test_a_failed_update_says_why_and_waits_for_enter(tmp_path):
    root, update = fake_install(tmp_path, "param($InstallRoot)\nthrow 'no network'\n")
    started = time.time()
    done = subprocess.run(update_command(update, root), input="\n", capture_output=True,
                          text=True, timeout=60)  # fmt: skip
    assert "no network" in done.stdout + done.stderr
    assert time.time() - started < 60

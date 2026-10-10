"""Is there a newer YapTracker? (#46) Once a day, the app asks GitHub for its releases.

This is the only network call the app itself makes (CLAUDE.md: local-only, with this exception):
one GET of the repo's release list, nothing sent but the request. On by default, switchable in
Settings -> About. Never during a match: it waits until the match is over. Offline or rate
limited: one log line, the next try a day later. Pre-releases count while YapTracker is on
v0; from v1.0.0 on, only stable releases.

Update now runs the update.ps1 bundled with the app (the same script as by hand): from %TEMP%,
since the app folder is replaced, in its own console with the download bar. YapTracker quits;
the script swaps the app folder, never touches the data folder and starts YapTracker again.
"""

import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

REPO = "6uhrmittag/Overwatch-YapTracker"
# 100 like update.ps1 (#281): enough to find the installed version for "What's new since".
URL = f"https://api.github.com/repos/{REPO}/releases?per_page=100"
DAY_S = 24 * 60 * 60
FIRST_CHECK_S = 30  # after the start: the app comes up first
POLL_S = 60  # how often the thread looks whether a check is due (and the match is over)
NOTES_CAP = 15  # bullets in What's new, like update.ps1


def fetch_releases() -> list[dict]:
    request = urllib.request.Request(
        URL, headers={"User-Agent": "YapTracker", "Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def version(text: str | None) -> tuple[int, int, int] | None:
    """(0, 5, 412) from "v0.5.412" or "0.5.412"; None for anything else ("0.0.0.dev0" is 0.0.0)."""
    found = re.match(r"v?(\d+)\.(\d+)\.(\d+)", text or "")
    return (int(found[1]), int(found[2]), int(found[3])) if found else None


def candidates(releases: list[dict], installed: str) -> list[dict]:
    """The releases that count, newest first: no drafts; no pre-releases once on v1 or later."""
    stable = (version(installed) or (0, 0, 0)) >= (1, 0, 0)
    found = [r for r in releases if not r.get("draft") and version(r.get("tag_name"))]
    found = [r for r in found if not (stable and r.get("prerelease"))]
    return sorted(found, key=lambda r: version(r["tag_name"]), reverse=True)


def whats_new(releases: list[dict], installed: str) -> list[str]:
    """The release notes since the installed version, newest first (update.ps1's #281 text):
    every "- " bullet once, "Behind the scenes" ones only counted, at most NOTES_CAP."""
    mine = version(installed)
    bullets: list[str] = []
    behind = 0
    for release in releases:
        if mine is not None and version(release["tag_name"]) <= mine:
            break
        for line in (release.get("body") or "").splitlines():
            if not line.startswith("- "):
                continue
            if line.startswith("- Behind the scenes"):
                behind += 1
            elif line[2:] not in bullets:
                bullets.append(line[2:])
    notes = bullets[:NOTES_CAP]
    if len(bullets) > NOTES_CAP:
        notes.append(f"... and {len(bullets) - NOTES_CAP} more")
    if behind:
        notes.append(f"(+ {behind} behind-the-scenes change{'s' if behind > 1 else ''})")
    return notes


@dataclass
class Found:
    """What the last check found."""

    at: float
    newest: str | None = None  # a newer version's tag, e.g. "v0.5.412"; None: up to date
    notes: list[str] = field(default_factory=list)
    error: str | None = None  # the check failed (offline, rate limit)


class UpdateCheck:
    def __init__(
        self,
        installed: str,
        enabled: Callable[[], bool],
        busy: Callable[[], bool] = lambda: False,
        fetch: Callable[[], list[dict]] = fetch_releases,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.installed = installed
        self._enabled, self._busy, self._fetch, self._clock = enabled, busy, fetch, clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.found: Found | None = None

    @property
    def newest(self) -> str | None:
        """A newer version's tag, for the Live banner; None when up to date or never checked."""
        found = self.found
        return found.newest if found is not None else None

    def due(self) -> bool:
        """Switched on, not in a match, and the last check (or failure) is a day old."""
        found = self.found
        return (
            self._enabled()
            and not self._busy()
            and (found is None or self._clock() - found.at >= DAY_S)
        )

    def check(self) -> Found:
        """Ask GitHub now (also Settings -> About -> Check now). Never raises."""
        with self._lock:
            now = self._clock()
            try:
                releases = candidates(self._fetch(), self.installed)
            except Exception as error:  # offline, rate limit, garbage: silent, tomorrow again
                found = Found(now, error=f"{type(error).__name__}: {error}"[:200])
                log.info("update: check failed (%s)", found.error)
            else:
                newest = releases[0]["tag_name"] if releases else None
                if newest and version(newest) > (version(self.installed) or (0, 0, 0)):
                    found = Found(now, newest, whats_new(releases, self.installed))
                    log.info("update: %s is out (this is v%s)", newest, self.installed)
                else:
                    found = Found(now)
                    log.info("update: up to date (v%s)", self.installed)
            self.found = found
            return found

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="update check", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        self._stop.wait(FIRST_CHECK_S)
        while not self._stop.is_set():
            if self.due():
                self.check()
            self._stop.wait(POLL_S)


def install_root() -> Path | None:
    """<root>\\app\\YapTracker.exe -> <root>, the folder update.ps1 installs into. None when this
    isn't an installed YapTracker (run from source, --dev, or unpacked somewhere else)."""
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        return None
    app_dir = Path(sys.executable).parent
    return app_dir.parent if app_dir.name.lower() == "app" else None


def bundled_script() -> Path | None:
    """tools/update.ps1 as the build bundled it (packaging/yaptracker.spec)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    script = base / "tools" / "update.ps1"
    return script if script.exists() else None


def _quoted(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def update_command(script: Path, root: Path) -> list[str]:
    """PowerShell running update.ps1, and afterwards making sure YapTracker runs again: also when
    the script stops early (already the newest) or fails (offline: the old app stays, the console
    stays open so the reason can be read)."""
    exe = _quoted(root / "app" / "YapTracker.exe")
    code = (
        f"try {{ & {_quoted(script)} -InstallRoot {_quoted(root)} }} catch {{ "
        "Write-Host $_ -ForegroundColor Red; "
        "Read-Host 'The update failed, YapTracker stays as it was. Press Enter to start it' }; "
        "if (-not (Get-Process YapTracker -ErrorAction SilentlyContinue)) "
        f"{{ Start-Process {exe} }}"
    )
    return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", code]


def cannot_update_now(match_running: bool = False) -> str | None:
    """Why Update now can't run now, or None when it can."""
    if match_running:
        return "Updates wait until the match is over."
    if install_root() is None:
        return "Only in the installed YapTracker. Here: run update.ps1 from the tools folder."
    if bundled_script() is None:
        return "update.ps1 is missing from this build: run it from the tools folder."
    return None


def start_update(newest: str | None) -> None:
    """Start update.ps1 in its own console; the caller quits YapTracker next. Raises when it
    can't start (then YapTracker just keeps running)."""
    script, root = bundled_script(), install_root()
    if script is None or root is None:
        raise RuntimeError(cannot_update_now())
    copy = Path(tempfile.gettempdir()) / "YapTracker-update.ps1"
    shutil.copyfile(script, copy)
    subprocess.Popen(update_command(copy, root), cwd=tempfile.gettempdir(),
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))  # fmt: skip
    log.info("update: Update now to %s, update.ps1 started for %s, quitting", newest, root)

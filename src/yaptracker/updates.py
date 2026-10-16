"""Is there a newer YapTracker? (#46) Once a day, the app asks GitHub for its releases.

This is the only network call the app itself makes (CLAUDE.md: local-only, with this exception):
one GET of the repo's release list, nothing sent but the request. On by default, switchable in
Settings -> About. Never during a match: it waits until the match is over. Offline or rate
limited: one log line, the next try a day later. Stable releases only, unless "Get test
versions" is on (#454), or no stable release exists yet (before v1.0.0 every build was a
pre-release). A stable release is a promoted pre-release, the same build: the promote workflow
writes "Same build as v1.1.0-pre.512" in its notes, and that build counts as up to date with it.

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


Version = tuple[int, int, int, int, int]
NOTHING: Version = (0, 0, 0, 0, 0)
SAME_BUILD = re.compile(r"Same build as v?(\d+\.\d+\.\d+(?:-pre\.\d+)?)")


def version(text: str | None) -> Version | None:
    """(0, 5, 412, 1, 0) from "v0.5.412" or "0.5.412"; (1, 1, 0, 0, 5) from "v1.1.0-pre.5", a
    test version that comes before "v1.1.0" (1, 1, 0, 1, 0). None for anything else
    ("0.0.0.dev0" is 0.0.0)."""
    found = re.match(r"v?(\d+)\.(\d+)\.(\d+)(?:-pre\.(\d+))?", text or "")
    if not found:
        return None
    pre = found[4]
    return int(found[1]), int(found[2]), int(found[3]), 0 if pre else 1, int(pre or 0)


def candidates(releases: list[dict], installed: str, test_versions: bool = False) -> list[dict]:
    """The releases that count, newest first: no drafts; stable releases only, unless test
    versions are wanted or there is no stable release yet."""
    found = [r for r in releases if not r.get("draft") and version(r.get("tag_name"))]
    if not test_versions and any(not r.get("prerelease") for r in found):
        found = [r for r in found if not r.get("prerelease")]
    return sorted(found, key=lambda r: version(r["tag_name"]), reverse=True)


def newer(release: dict, installed: str) -> bool:
    """A later version than the installed one, and not the very build that runs (a promoted
    stable release has the pre-release's build inside, with its version)."""
    same = SAME_BUILD.search(release.get("body") or "")
    if same and version(same[1]) == version(installed):
        return False
    return version(release["tag_name"]) > (version(installed) or NOTHING)


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
        cache: Path | None = None,
        test_versions: Callable[[], bool] = lambda: False,
    ) -> None:
        self.installed = installed
        self._enabled, self._busy, self._fetch, self._clock = enabled, busy, fetch, clock
        self._test_versions = test_versions  # "Get test versions" in Settings (#454)
        self._cache = cache  # the releases last fetched, for What's new after an update (#412)
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
                releases = candidates(self._fetch(), self.installed, self._test_versions())
                save_releases(self._cache, releases)
            except Exception as error:  # offline, rate limit, garbage: silent, tomorrow again
                found = Found(now, error=f"{type(error).__name__}: {error}"[:200])
                log.info("update: check failed (%s)", found.error)
            else:
                newest = releases[0]["tag_name"] if releases else None
                if newest and newer(releases[0], self.installed):
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


# What's new after an update (#412) ----------------------------------------------------------

_KEPT = ("tag_name", "body", "prerelease", "draft")


def save_releases(path: Path | None, releases: list[dict]) -> None:
    """The fetched releases, trimmed to what What's new needs; no-op without a path."""
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    trimmed = [{k: r.get(k) for k in _KEPT} for r in releases]
    path.write_text(json.dumps(trimmed, ensure_ascii=False), encoding="utf-8")


def _load(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_notes(path: Path, before: str, after: str | None, notes: list[str]) -> None:
    """Update now: the notes it already has, for the first start of the new version."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"from": before.lstrip("v"), "to": (after or "").lstrip("v"), "notes": notes}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def notes_for(installed: str, notes_file: Path) -> dict | None:
    """What's new in the installed version, as last shown (#412): About can show it again."""
    saved = _load(notes_file)
    if (
        isinstance(saved, dict)
        and saved.get("notes")
        and version(saved.get("to")) == version(installed)
    ):
        return saved
    return None


def after_update(installed: str, last_run: str | None, notes_file: Path, cache: Path,
                 fetch: Callable[[], list[dict]] = fetch_releases) -> dict | None:  # fmt: skip
    """What's new at the first start of a new version: {"from", "to", "notes"} (notes None:
    offline, no list), or None (fresh install, same version, downgrade). From what Update now
    saved, else the releases the daily check cached, else one fetch (the allowed URL)."""
    now, before = version(installed), version(last_run)
    if now is None or before is None or now <= before:
        return None
    saved = _load(notes_file)
    if (
        isinstance(saved, dict)
        and saved.get("notes")
        and (
            version(saved.get("to")),
            version(saved.get("from")),
        )
        == (now, before)
    ):
        return {"from": last_run, "to": installed, "notes": saved["notes"]}
    releases = _load(cache)
    if not isinstance(releases, list) or not any(version(r.get("tag_name")) == now
                                                 for r in releases):  # fmt: skip
        try:
            releases = candidates(fetch(), installed, test_versions=True)
            save_releases(cache, releases)
        except Exception as error:
            log.info("update: no notes for What's new (%s)", type(error).__name__)
            return {"from": last_run, "to": installed, "notes": None}
    mine = [r for r in releases if version(r.get("tag_name")) and version(r["tag_name"]) <= now]
    found = {"from": last_run, "to": installed, "notes": whats_new(mine, last_run)}
    notes_file.write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
    return found


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


def update_command(script: Path, root: Path, test_versions: bool = False) -> list[str]:
    """PowerShell running update.ps1, and afterwards making sure YapTracker runs again: also when
    the script stops early (already the newest) or fails (offline: the old app stays, the console
    stays open so the reason can be read). test_versions: the same choice as the check (#454)."""
    exe = _quoted(root / "app" / "YapTracker.exe")
    pre = " -PreRelease" if test_versions else ""
    code = (
        f"try {{ & {_quoted(script)} -InstallRoot {_quoted(root)}{pre} }} catch {{ "
        "Write-Host $_ -ForegroundColor Red; "
        "Read-Host 'The update failed, YapTracker stays as it was. Press Enter to start it' }; "
        "if (-not (Get-Process YapTracker -ErrorAction SilentlyContinue)) "
        f"{{ Start-Process {exe} }}"
    )
    return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", code]


def cannot_update_now() -> str | None:
    """Why Update now can't run here, or None when it can. A running match doesn't stop it
    (Marv, #416): you decide when to update."""
    if install_root() is None:
        return "Only in the installed YapTracker. Here: run update.ps1 from the tools folder."
    if bundled_script() is None:
        return "update.ps1 is missing from this build: run it from the tools folder."
    return None


def start_update(newest: str | None, test_versions: bool = False) -> None:
    """Start update.ps1 in its own console; the caller quits YapTracker next. Raises when it
    can't start (then YapTracker just keeps running)."""
    script, root = bundled_script(), install_root()
    if script is None or root is None:
        raise RuntimeError(cannot_update_now())
    copy = Path(tempfile.gettempdir()) / "YapTracker-update.ps1"
    shutil.copyfile(script, copy)
    subprocess.Popen(update_command(copy, root, test_versions), cwd=tempfile.gettempdir(),
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))  # fmt: skip
    log.info("update: Update now to %s, update.ps1 started for %s, quitting", newest, root)

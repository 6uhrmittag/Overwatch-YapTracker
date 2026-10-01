"""Daily backups (#125): one corrupted file or bad update must never cost months of yaps.

data\\backups\\yaptracker-<yyyy-mm-dd>.db, made with SQLite's online backup API (safe while
the app runs), at most once a day and never while Overwatch is being captured. The last 7
days and the newest backup of each of the last 4 weeks are kept. The pre-migration backups
(yaptracker-v<N>-...) are a different kind and are never touched here.
"""

import logging
import re
import threading
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

KEEP_DAILY = 7
KEEP_WEEKLY = 4
CHECK_EVERY_S = 10 * 60
_DAILY = re.compile(r"^yaptracker-(\d{4})-(\d{2})-(\d{2})\.db$")


def daily_backups(folder: Path) -> list[tuple[date, Path]]:
    """Newest first."""
    found = []
    if folder.exists():
        for path in folder.iterdir():
            if m := _DAILY.match(path.name):
                found.append((date(*map(int, m.groups())), path))
    return sorted(found, reverse=True)


def prune(folder: Path) -> None:
    backups = daily_backups(folder)
    keep = {path for _, path in backups[:KEEP_DAILY]}
    weeks: dict[tuple[int, int], Path] = {}
    for day, path in backups:  # newest first: the first one seen of a week is its newest
        weeks.setdefault(day.isocalendar()[:2], path)
    keep |= set(list(weeks.values())[:KEEP_WEEKLY])
    for _, path in backups:
        if path not in keep:
            path.unlink()


class DailyBackup:
    def __init__(
        self,
        backup: Callable[[Path], None],
        folder: Path,
        busy: Callable[[], bool],
        today: Callable[[], date] = date.today,
    ) -> None:
        self._backup, self._folder, self._busy, self._today = backup, folder, busy, today
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> Path | None:
        """Today's backup, unless it exists already or Overwatch is being captured."""
        backups = daily_backups(self._folder)
        if (backups and backups[0][0] >= self._today()) or self._busy():
            return None
        self._folder.mkdir(parents=True, exist_ok=True)
        target = self._folder / f"yaptracker-{self._today().isoformat()}.db"
        started = time.perf_counter()
        self._backup(target)
        prune(self._folder)
        log.info("daily backup %s in %.2f s", target.name, time.perf_counter() - started)
        return target

    def start(self) -> None:
        """Checks at start and every 10 minutes: the first quiet moment of a day backs up."""
        self._thread = threading.Thread(target=self._run, name="daily backup", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # logged; tried again at the next check
                log.exception("daily backup failed")
            self._stop.wait(CHECK_EVERY_S)


def last_backup(folder: Path) -> tuple[float, int] | None:
    """(time of the newest daily backup, how many are kept) for Settings."""
    backups = daily_backups(folder)
    return (backups[0][1].stat().st_mtime, len(backups)) if backups else None

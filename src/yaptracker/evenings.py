"""One quality line per evening (#379): "did the reading get worse?" answered by comparing
evenings, not by digging through the log and the database.

When an evening ends (Overwatch closed, YapTracker quits, or the next evening starts) the log
gets an `evening` line and data/evenings.json keeps it for Settings -> About. Matches, maps and
lines come from the database; CPU and read modes from the reader's minute lines in the log
("chat reading: 16 frames ... (best 16); whole app: 23.1 % of a core"). The evenings since
2026-10-01 are filled in once, at the first start with this, as a baseline.
"""

import json
import logging
import os
import re
import threading
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from yaptracker import game_lists, logs, paths
from yaptracker.store.repo import SessionRow, Store

log = logging.getLogger(__name__)

BASELINE = "2026-10-01"
LOW_CONFIDENCE = 0.8  # what the read preview marks as unsure
KEEP = 90  # evenings in the file
READ_MODES = ("best", "light", "after")
_MINUTE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO yaptracker\.reader: chat reading: \d+ frames, "
    r"\d+ ms CPU each(?: \(([^)]*)\))?; whole app: ([\d.]+) %",
    re.MULTILINE,
)
_CLOCK = "%Y-%m-%d %H:%M:%S"


def log_files(since: float = 0) -> list[Path]:
    """The app log and its rotated files written to since `since`, oldest first."""
    base = paths.log_file()
    files = [base.with_name(f"{base.name}.{n}") for n in range(logs.BACKUPS, 0, -1)] + [base]
    return [f for f in files if f.exists() and f.stat().st_mtime >= since]


def minutes(files: list[Path]) -> list[tuple[str, str, float]]:
    """The reader's minute lines: (local time, read modes like "light 31, best 9", CPU %)."""
    found = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found += [(m[1], m[2] or "", float(m[3])) for m in _MINUTE.finditer(text)]
    return found


def summarize(store: Store, session: SessionRow, logged: list[tuple]) -> dict | None:
    """The evening's numbers; None when it had no match."""
    played, (count, confidence, low, glyphs, fixed) = store.evening(session.id, LOW_CONFIDENCE)
    if not played:
        return None
    hero = [m for m in played if m[0] == "heroselect"]
    sources = Counter(m[0] for m in played)
    start, end = (time.strftime(_CLOCK, time.localtime(t)) for t in (session.started_at,
                                                                    session.ended_at))  # fmt: skip
    cpu, modes = [], Counter()
    for clock, read, whole in logged:
        if start <= clock <= end:
            cpu.append(whole)
            for part in filter(None, read.split(", ")):
                mode, _, n = part.rpartition(" ")
                modes[mode] += int(n)
    return {
        "session": session.id,
        "date": start[:10],
        "matches": len(played),
        "heroselect": sources["heroselect"],
        "gap": len(played) - sources["heroselect"] - sources["hotkey"],  # 'endscreen': old
        "hand": sources["hotkey"],
        "map": _share(sum(game_lists.map_name(m[1]) is not None for m in hero), len(hero)),
        "queue": _share(sum(game_lists.queue(m[2]) is not None for m in hero), len(hero)),
        "result": _share(sum(m[3] is not None for m in played), len(played)),
        "missed_ends": sum(m[3] is None for m in played),
        "lines": count,
        "confidence": None if confidence is None else round(confidence, 3),
        "low": _share(low, count),
        "glyphs": _share(glyphs, count),
        "fixed": fixed,
        "modes": {mode: modes[mode] for mode in READ_MODES} if modes else None,
        "cpu": round(sum(cpu) / len(cpu), 1) if cpu else None,
    }


def line(e: dict) -> str:
    """The log line: `evening 2026-10-10: 7 matches (hero select 6, gap 1, hand 0) · ...`."""
    modes = ", ".join(f"{k} {n}" for k, n in e["modes"].items()) if e["modes"] else "-"
    confidence = "-" if e["confidence"] is None else f"{e['confidence']:.2f}"
    return (
        f"evening {e['date']}: {e['matches']} matches (hero select {e['heroselect']}, "
        f"gap {e['gap']}, hand {e['hand']}) · map known {percent(e['map'])} · queue known "
        f"{percent(e['queue'])} · result {percent(e['result'])} · missed ends "
        f"{e['missed_ends']} · lines {e['lines']} (avg confidence {confidence}, low-confidence "
        f"{percent(e['low'])}, ◇ {percent(e['glyphs'])}) · fixed by hand {e['fixed']} · read "
        f"modes {modes} · whole app {percent(e['cpu'])} of a core"
    )


def percent(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f} %"


def _share(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


class Evenings:
    """data/evenings.json: the last KEEP evenings, oldest first."""

    def __init__(
        self,
        path: Path,
        store: Store,
        files: Callable[[float], list[Path]] = log_files,
    ) -> None:
        self._path, self._store, self._files = path, store, files
        self._lock = threading.Lock()  # the capture watcher and the shutdown both record

    def record(self, session_id: int | None) -> None:
        """The evening is over (or seems to be): its line to the log, unless it's unchanged."""
        try:
            session = next((s for s in self._store.sessions() if s.id == session_id), None)
            if session is None:
                return
            evening = summarize(self._store, session, minutes(self._files(session.started_at)))
            with self._lock:
                if evening is not None and evening not in self._load():
                    log.info("%s", line(evening))
                    self._save([evening])
        except Exception:  # never in the way of capture or quitting
            log.exception("the evening line failed")

    def last(self, n: int = 7) -> list[dict]:
        """The newest `n` evenings, newest first."""
        with self._lock:
            return self._load()[-n:][::-1]

    def backfill(self, since: str = BASELINE) -> None:
        """Once, while there's no file yet: the evenings since `since`, as a baseline."""
        with self._lock:
            if self._path.exists():
                return
            start = time.mktime(time.strptime(since, "%Y-%m-%d"))
            logged = minutes(self._files(start))
            sessions = [s for s in self._store.sessions() if s.started_at >= start]
            done = [e for s in reversed(sessions) if (e := summarize(self._store, s, logged))]
            for evening in done:
                log.info("%s (filled in)", line(evening))
            self._save(done)  # an empty file too: filled in once

    def _load(self) -> list[dict]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _save(self, new: list[dict]) -> None:
        ids = {e["session"] for e in new}
        kept = [e for e in self._load() if e["session"] not in ids] + new
        kept = sorted(kept, key=lambda e: e["session"])[-KEEP:]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        part = self._path.with_suffix(".part")
        part.write_text(json.dumps(kept, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(part, self._path)

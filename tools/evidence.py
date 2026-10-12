"""Answer the waiting issues from a data folder (#437): logs (rotated ones too), a snapshot of the
database and debug/. Plain text with ids only, ready to paste into an issue comment.

    python tools/evidence.py /mnt/c/Users/marvi/AppData/Local/YapTracker/data

Read-only. The database is copied while it doesn't change (a running YapTracker writes to it),
read into memory, and the copy on disk is deleted at once: it holds names and chat.
Everything is grouped by evening: like Sessions (#440), an evening runs until 05:00.
"""

import re
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from yaptracker import evenings, logs, reading_mode
from yaptracker.store.repo import Store

_TIME = r"^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d),\d+ \w+ yaptracker\.[\w.]+: "
VERSION = re.compile(_TIME + r"system: YapTracker v(\S+)")
MINUTE = re.compile(_TIME + r"chat reading: \d+ frames, .*whole app: ([\d.]+) %")
THREADS = re.compile(_TIME + r"cpu threads \(([^)]*)\): (.*)")
CAPTURE = re.compile(_TIME + r"capture: asking Windows for ([\d.]+) frames a second \(([^)]*)\)")
FPS = re.compile(_TIME + r"game fps \(Overwatch overlay\): median (\d+), .* — (running|paused), "
                 r"(in match|between matches)")  # fmt: skip
MODE = re.compile(_TIME + r"reading: (best|light|after) \(")
EVENING = re.compile(_TIME + r"(evening \d{4}-\d\d-\d\d: .*)")
ROUND = re.compile(_TIME + r"match (\d+): round (\d+)")
TIDIED = re.compile(_TIME + r"(tidied match \d+: .*?removed)")
SHARE = re.compile(r"(.+?) ([\d.]+) %(?:, |$)")  # "capture watcher 9.8 %, pywebview-js 1.0 %"
FPS_BAR = 5.0  # % of in-match FPS YapTracker may cost (Definition of done)
CUT_H = 5  # an evening runs until 05:00 (#440)
END_SLACK_S = 120  # an end sample is saved a moment after its match ended
_COMPETITIVE = ", ".join(f"'{q}'" for q in sorted(reading_mode.COMPETITIVE_QUEUES))  # + GEWERTET
_PLAYED = (
    "(EXISTS (SELECT 1 FROM live_messages c WHERE c.match_id = m.id) OR m.outcome IS NOT NULL)"
)


def evening_of(date: str, clock: str) -> str:
    """'2026-10-11' for anything from Oct 11, 05:00 to Oct 12, 04:59."""
    moment = datetime.strptime(f"{date} {clock}", "%Y-%m-%d %H:%M:%S") - timedelta(hours=CUT_H)
    return moment.date().isoformat()


def log_files(data: Path) -> list[Path]:
    """The log and its rotated files, oldest first (yaptracker.log.4 ... .1, yaptracker.log)."""
    base = data / "logs" / "yaptracker.log"
    return [base.with_name(f"{base.name}.{n}") for n in range(logs.BACKUPS, 0, -1)] + [base]


def log_lines(files: list[Path]) -> list[str]:
    lines: list[str] = []
    for path in files:
        try:
            lines += path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:  # not there, or rotated away just now
            continue
    return lines


def database(data: Path) -> sqlite3.Connection | None:
    """The database (with its WAL) in memory, copied while neither file changed; None without
    one. The copy on disk goes away before this returns."""
    source = data / "yaptracker.db"
    if not source.exists():
        return None
    parts = [source, source.with_name(source.name + "-wal")]

    def state() -> list:
        return [(p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None for p in parts]

    with tempfile.TemporaryDirectory(prefix="evidence-") as folder:
        for _ in range(5):  # a write in between: copy again (the last try is used anyway)
            before = state()
            for part in parts:
                if part.exists():
                    shutil.copy(part, Path(folder) / part.name)
            if state() == before:
                break
            time.sleep(1)
        copy, memory = sqlite3.connect(Path(folder) / source.name), sqlite3.connect(":memory:")
        try:
            copy.backup(memory)
        finally:
            copy.close()
    return memory


def _median(values: list[float]) -> str:
    return f"{statistics.median(values):.0f}" if values else "-"


def _version_key(version: str) -> tuple:
    return tuple(int(p) if p.isdigit() else 0 for p in version.split("."))


def scan(lines: list[str]) -> dict:
    """Everything the log says, per evening: versions, CPU, in-match threads, FPS by version,
    reading mode and state. The version and mode of a line are the last ones logged before it."""
    found: dict = {"versions": defaultdict(set), "cpu": defaultdict(list),
                   "capture": defaultdict(set), "threads": defaultdict(Counter),
                   "thread_minutes": Counter(), "fps": defaultdict(list), "evenings": [],
                   "rounds": [], "tidied": []}  # fmt: skip
    version, mode = "?", "?"
    for line in lines:
        if not (m := re.match(_TIME, line)):
            continue
        day = evening_of(m[1], m[2])
        if m := VERSION.match(line):
            version = m[3]
            found["versions"][day].add(version)
        elif m := MODE.match(line):
            mode = m[3]
        elif m := MINUTE.match(line):
            found["cpu"][day].append(float(m[3]))
            found["versions"][day].add(version)  # still running from an earlier day too
        elif m := THREADS.match(line):
            if m[3] == "in match":  # where the game feels it; idle minutes would thin it out
                found["thread_minutes"][day] += 1
                for name, share in SHARE.findall(m[4]):
                    found["threads"][day][name] += float(share)
        elif m := CAPTURE.match(line):
            found["capture"][day].add(f"{m[3]} fps {m[4]}")
        elif m := FPS.match(line):
            if m[5] == "in match":
                found["fps"][(day, version, mode, m[4])].append(float(m[3]))
        elif m := EVENING.match(line):
            found["evenings"].append((day, "filled in later" if "(filled in)" in line
                                      else f"v{version}", m[3]))  # fmt: skip
        elif m := ROUND.match(line):
            found["rounds"].append((day, int(m[3]), int(m[4])))
        elif m := TIDIED.match(line):
            found["tidied"].append((day, m[3]))
    return found


def fps_verdict(running: list[float], paused: list[float]) -> str:
    """In-match FPS, running vs paused, against the bar (≤ 5 % of in-match FPS)."""
    if not paused:
        return (f"no paused in-match samples (running median {_median(running)} fps, "
                f"n={len(running)}): one paused match settles it")  # fmt: skip
    if not running:
        return f"no running in-match samples (paused median {_median(paused)} fps)"
    run, rest = statistics.median(running), statistics.median(paused)
    cost = 100 * (rest - run) / rest if rest else 0.0
    verdict = "within" if cost <= FPS_BAR else "over"
    return (f"running {run:.0f} fps vs paused {rest:.0f} fps: costs {cost:.1f} % "
            f"({verdict} the {FPS_BAR:.0f} % bar)")  # fmt: skip


def fps_verdicts(fps: dict, days: set[str] | None = None) -> list[str]:
    """One verdict per version and reading mode, never a mix: running samples of that mode
    against the paused ones of the same version (paused, the mode doesn't matter)."""
    running, paused = defaultdict(list), defaultdict(list)
    for (day, version, mode, state), values in fps.items():
        if days is None or day in days:
            (running[(version, mode)] if state == "running" else paused[version]).extend(values)
    order = sorted(running, key=lambda k: (_version_key(k[0]), k[1]))
    return [f"v{v} {mode}: {fps_verdict(running[(v, mode)], paused[v])}" for v, mode in order] \
        or ["no running in-match samples"]  # fmt: skip


def report(data: Path) -> str:
    """The plain-text report for the data folder."""
    files = log_files(data)
    found = scan(log_lines(files))
    happened = defaultdict(Counter)  # evening -> kind -> how many (the app's own patterns)
    for clock, kind, n in evenings.scan(files)[1]:
        happened[evening_of(clock[:10], clock[11:])][kind] += n
    db = database(data)
    try:
        return "\n".join(_sections(data, found, happened, db)) + "\n"
    finally:
        if db is not None:
            db.close()


def _sections(data: Path, found: dict, happened: dict, db: sqlite3.Connection | None) -> list:
    out = [f"Evidence from {data.name}/ (ids only, evenings run until 0{CUT_H}:00)", ""]

    out.append("## #115 CPU (per evening)")
    for day in sorted(set(found["cpu"]) | set(found["thread_minutes"])):
        versions = sorted(found["versions"].get(day, set()) - {"?"}, key=_version_key)
        tag = f"v{', '.join(versions)}" if versions else "v?"
        cpu = found["cpu"].get(day, [])
        out.append(f"- {day} ({tag}): whole app avg {statistics.mean(cpu):.1f} % of a core "
                   f"(n={len(cpu)})" if cpu else f"- {day} ({tag}): no CPU minutes")  # fmt: skip
        n = found["thread_minutes"][day]
        shares = sorted(found["threads"][day].items(), key=lambda kv: -kv[1])
        threads = ", ".join(f"{name} {total / n:.1f} %" for name, total in shares) if n else "-"
        capture = "; ".join(sorted(found["capture"].get(day, []))) or "-"
        out.append(f"  threads in match ({n} min): {threads}; seen but not stored "
                   f"{happened[day]['unstored']}; capture {capture}")  # fmt: skip
    recent = sorted({day for day, _, _ in found["evenings"]})[-7:]  # every line of those evenings
    out += [f"  {tag}: {text}" for day, tag, text in found["evenings"] if day in recent]
    out.append("")

    out.append("## #187 / #330 FPS in match (median of the minute medians)")
    for (day, version, mode, state), values in sorted(found["fps"].items()):
        out.append(f"- {day} v{version} {mode} {state}: {_median(values)} fps (n={len(values)})")
    out += [f"- verdict {line}" for line in fps_verdicts(found["fps"])]
    out.append("")

    out.append("## #372 Competitive")
    if db is not None:
        comp = db.execute(f"SELECT m.id, date(m.started_at, 'unixepoch', 'localtime') FROM "
                          f"matches m WHERE upper(m.mode) IN ({_COMPETITIVE}) AND {_PLAYED} "
                          "ORDER BY m.id").fetchall()  # fmt: skip
        out.append(f"- Competitive matches: {len(comp)}"
                   + (f" ({', '.join(f'#{i} {d}' for i, d in comp)})" if comp else ""))  # fmt: skip
        maps = db.execute(f"SELECT date(MIN(m.started_at), 'unixepoch', 'localtime'), m.map, "
                          f"COUNT(*) FROM matches m WHERE m.map IS NOT NULL AND upper(m.mode) IN "
                          f"({_COMPETITIVE}) AND {_PLAYED} GROUP BY m.session_id, m.map "
                          "HAVING COUNT(*) > 1 ORDER BY 1, 3 DESC").fetchall()  # fmt: skip
        out.append("- same map twice in one session, Competitive: "
                   + ("; ".join(f"{d} {m} ×{n}" for d, m, n in maps) or "none"))  # fmt: skip
    rounds = [f"#{match} round {n} ({day})" for day, match, n in found["rounds"]]
    out.append(f"- later rounds kept in their match: {', '.join(rounds) or 'none'}")
    out.append("")

    out.append("## #348 Ranked end samples")
    ends = sorted((data / "debug").glob("*/*-end"))
    ranked = []
    if db is not None and ends:
        ended = [row[0] for row in db.execute(
            f"SELECT m.ended_at FROM matches m WHERE upper(m.mode) IN ({_COMPETITIVE}) "
            "AND m.ended_at IS NOT NULL")]  # fmt: skip
        for end in ends:
            try:
                ts = time.mktime(time.strptime(f"{end.parent.name} {end.name[:8]}",
                                               "%Y-%m-%d %H-%M-%S"))  # fmt: skip
            except ValueError:
                continue
            if any(abs(ts - t) <= END_SLACK_S for t in ended):
                ranked.append(f"{end.parent.name}/{end.name}")
    out.append(f"- end samples: {len(ends)}; of a Competitive match: "
               + (", ".join(ranked) if ranked else "none"))  # fmt: skip
    out.append("")

    last = max(found["cpu"], default=None)  # the newest evening YapTracker read chat
    out.append(f"## #34 Acceptance evening ({last or 'none yet'})")
    if db is not None:
        out.append(f"- players with notes now: {Store(db).players_with_notes()} (the bar: 3)")
    if last:
        shown, after = happened[last]["familiar"], happened[last]["familiar_after"]
        out.append(f"- familiar faces shown: {shown + after} (after the match {after})")
        out += [f"- FPS {line}" for line in fps_verdicts(found["fps"], {last})]
        tidied = [text for day, text in found["tidied"] if day == last]
        out.append(f"- tidy-ups logged: {len(tidied)}"
                   + (f" (last: {tidied[-1]})" if tidied else ""))  # fmt: skip
    return out


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.exit("usage: python tools/evidence.py <YapTracker data folder>")
    if hasattr(sys.stdout, "reconfigure"):  # "◇" in evening lines, also into a file or | clip
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(report(Path(args[0])))


if __name__ == "__main__":
    main()

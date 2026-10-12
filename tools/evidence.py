"""Answer the waiting issues from a data folder (#437): logs (rotated ones too), a copy of the
database and debug/. Plain text with ids only, ready to paste into an issue comment.

    python tools/evidence.py /mnt/c/Users/marvi/AppData/Local/YapTracker/data

Read-only: the database is copied first, so a running YapTracker is never in the way.
"""

import re
import shutil
import sqlite3
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

_TIME = r"^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d),\d+ \w+ yaptracker\.[\w.]+: "
VERSION = re.compile(_TIME + r"system: YapTracker v(\S+)")
MINUTE = re.compile(_TIME + r"chat reading: \d+ frames, .*whole app: ([\d.]+) %")
THREADS = re.compile(_TIME + r"cpu threads \(([^)]*)\): (.*)")
UNSTORED = re.compile(_TIME + r"chat reading: (\d+) line\(s\) seen twice but never stored")
CAPTURE = re.compile(_TIME + r"capture: asking Windows for ([\d.]+) frames a second \(([^)]*)\)")
FPS = re.compile(_TIME + r"game fps \(Overwatch overlay\): median (\d+), .* — (running|paused), "
                 r"(in match|between matches)")  # fmt: skip
MODE = re.compile(_TIME + r"reading: (best|light|after) \(")
EVENING = re.compile(_TIME + r"(evening \d{4}-\d\d-\d\d: .*)")
ROUND = re.compile(_TIME + r"match (\d+): round (\d+)")
FAMILIAR = re.compile(_TIME + r"familiar face: player #(\d+)")
TIDIED = re.compile(_TIME + r"(tidied match \d+: .*?removed)")
FPS_BAR = 5.0  # % of in-match FPS YapTracker may cost (Definition of done)


def log_lines(data: Path) -> list[str]:
    """Every log line, oldest file first (yaptracker.log.N ... yaptracker.log)."""
    logs = data / "logs"
    rotated = sorted(logs.glob("yaptracker.log.*"), key=lambda p: -int(p.suffix[1:] or 0))
    files = [*rotated, logs / "yaptracker.log"]
    return [line for f in files if f.exists()
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines()]  # fmt: skip


def database(data: Path) -> sqlite3.Connection | None:
    """A read-only copy of the database (with its WAL), or None."""
    source = data / "yaptracker.db"
    if not source.exists():
        return None
    folder = Path(tempfile.mkdtemp(prefix="evidence-"))
    for suffix in ("", "-wal", "-shm"):
        if (part := source.with_name(source.name + suffix)).exists():
            shutil.copy(part, folder / part.name)
    return sqlite3.connect(folder / source.name)


def _median(values: list[float]) -> str:
    return f"{statistics.median(values):.0f}" if values else "-"


def scan(lines: list[str]) -> dict:
    """Everything the log says, per date: versions, CPU, threads, FPS by state and mode."""
    found: dict = {"versions": defaultdict(set), "cpu": defaultdict(list), "unstored": Counter(),
                   "threads": defaultdict(lambda: defaultdict(list)), "capture": defaultdict(set),
                   "fps": defaultdict(list), "evenings": [], "rounds": [], "familiar": Counter(),
                   "tidied": []}  # fmt: skip
    version, mode = "?", "?"  # the version and reading mode a line was written under
    for line in lines:
        if m := VERSION.match(line):
            version = m[3]
            found["versions"][m[1]].add(version)
        elif m := MODE.match(line):
            mode = m[3]
        elif m := MINUTE.match(line):
            found["cpu"][m[1]].append(float(m[3]))
        elif m := THREADS.match(line):
            for name, share in re.findall(r"([\w ]+?) ([\d.]+) %", m[4]):
                found["threads"][m[1]][name.strip(", ")].append(float(share))
        elif m := UNSTORED.match(line):
            found["unstored"][m[1]] += int(m[3])
        elif m := CAPTURE.match(line):
            found["capture"][m[1]].add(f"{m[3]} fps {m[4]}")
        elif m := FPS.match(line):
            if m[5] == "in match":
                found["fps"][(m[1], version, mode, m[4])].append(float(m[3]))
        elif m := EVENING.match(line):
            found["evenings"].append((m[1], version, m[3]))
        elif m := ROUND.match(line):
            found["rounds"].append((m[1], int(m[3]), int(m[4])))
        elif m := FAMILIAR.match(line):
            found["familiar"][m[1]] += 1
        elif m := TIDIED.match(line):
            found["tidied"].append((m[1], m[3]))
    return found


def fps_verdict(fps: dict) -> str:
    """In-match FPS, running vs paused, against the bar (≤ 5 % of in-match FPS)."""
    running = [v for (_, _, _, state), values in fps.items() if state == "running" for v in values]
    paused = [v for (_, _, _, state), values in fps.items() if state == "paused" for v in values]
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


def report(data: Path) -> str:
    """The plain-text report for the data folder."""
    found = scan(log_lines(data))
    db = database(data)
    out = [f"Evidence from {data.name}/ (ids only)", ""]

    out.append("## #115 CPU (per date)")
    dates = sorted(set(found["cpu"]) | set(found["threads"]) | set(found["unstored"]))
    for date in dates:
        versions = ", ".join(sorted(found["versions"].get(date, []))) or "?"
        cpu = found["cpu"].get(date, [])
        shares = {name: statistics.mean(v) for name, v in found["threads"][date].items()}
        order = sorted(shares.items(), key=lambda kv: -kv[1])
        threads = ", ".join(f"{name} {share:.1f} %" for name, share in order)
        capture = "; ".join(sorted(found["capture"].get(date, []))) or "-"
        out.append(f"- {date} (v{versions}): whole app avg {statistics.mean(cpu):.1f} % of a core"
                   if cpu else f"- {date} (v{versions}): no CPU minutes")  # fmt: skip
        out.append(f"  threads: {threads or '-'}; seen but not stored {found['unstored'][date]}; "
                   f"capture {capture}")  # fmt: skip
    for _date, version, text in found["evenings"][-7:]:
        out.append(f"  v{version}: {text}")
    out.append("")

    out.append("## #187 / #330 FPS in match (median of the minute medians)")
    if found["fps"]:
        for (date, version, mode, state), values in sorted(found["fps"].items()):
            out.append(f"- {date} v{version} {mode} {state}: {_median(values)} fps "
                       f"(n={len(values)})")  # fmt: skip
    out.append(f"- verdict: {fps_verdict(found['fps'])}")
    out.append("")

    out.append("## #372 Competitive")
    if db is not None:
        comp = db.execute("SELECT id, date(started_at, 'unixepoch', 'localtime') FROM matches "
                          "WHERE upper(mode) = 'COMPETITIVE' ORDER BY id").fetchall()  # fmt: skip
        out.append(f"- Competitive matches: {len(comp)}"
                   + (f" ({', '.join(f'#{i} {d}' for i, d in comp)})" if comp else ""))  # fmt: skip
        maps = db.execute("SELECT date(started_at, 'unixepoch', 'localtime'), map, COUNT(*) "
                          "FROM matches WHERE map IS NOT NULL GROUP BY 1, 2 HAVING COUNT(*) > 1 "
                          "ORDER BY 1, 3 DESC").fetchall()  # fmt: skip
        out.append("- same map more than once in an evening: "
                   + ("; ".join(f"{d} {m} ×{n}" for d, m, n in maps) or "none"))  # fmt: skip
    rounds = [f"#{match} round {n} ({date})" for date, match, n in found["rounds"]]
    out.append(f"- later rounds kept in their match: {', '.join(rounds) or 'none'}")
    out.append("")

    out.append("## #348 Ranked end samples")
    ends = sorted(p.parent.name + "/" + p.name for p in (data / "debug").glob("*/*-end"))
    ranked = []
    if db is not None and ends:
        windows = db.execute("SELECT strftime('%Y-%m-%d/%H-%M-%S', ended_at, 'unixepoch', "
                             "'localtime') FROM matches WHERE upper(mode) = 'COMPETITIVE' AND "
                             "ended_at IS NOT NULL").fetchall()  # fmt: skip
        stamps = {w[0][:-3] for w in windows}  # to the minute
        ranked = [e for e in ends if e[:-7] in stamps]
    out.append(f"- end samples: {len(ends)}; of a Competitive match: "
               + (", ".join(ranked) if ranked else "none"))  # fmt: skip
    out.append("")

    out.append("## #34 Acceptance evening")
    if db is not None:
        notes = db.execute("SELECT COUNT(*) FROM players WHERE trim(COALESCE(notes, '')) != ''"
                           ).fetchone()[0]  # fmt: skip
        out.append(f"- players with notes: {notes} (the bar: 3)")
    shown = sum(found["familiar"].values())
    out.append(f"- familiar faces shown: {shown}"
               + (f" ({', '.join(f'{d} {n}' for d, n in sorted(found['familiar'].items()))})"
                  if shown else ""))  # fmt: skip
    out.append(f"- FPS: {fps_verdict(found['fps'])}")
    out.append(f"- tidy-ups logged: {len(found['tidied'])}"
               + (f" (last: {found['tidied'][-1][1]})" if found["tidied"] else ""))  # fmt: skip
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.exit("usage: python tools/evidence.py <YapTracker data folder>")
    sys.stdout.write(report(Path(args[0])))


if __name__ == "__main__":
    main()

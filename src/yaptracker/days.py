"""Days (#440): Sessions lists the days you played, not the sessions kept behind the scenes.

A day runs until 05:00, so a late evening (21:48-01:00) stays one day under the date it began.
Within a day, BREAK_S or more between two matches is a break: the day view shows it as a quiet
divider, and the time played adds up the play blocks instead of first match to last.
The store works out each match's day in SQL (`MatchRow.day`); day_of is the same rule for a
moment that isn't a stored match (the Live snap's title).
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

CUT_H = 5  # a match that starts before 05:00 belongs to the day before
BREAK_S = 15 * 60  # longer than a queue plus hero select between two matches: a break


def day_of(ts: float) -> str:
    """'2026-10-11' for anything from Oct 11, 05:00 to Oct 12, 04:59 local time."""
    return (datetime.fromtimestamp(ts) - timedelta(hours=CUT_H)).date().isoformat()


def title(key: str, fmt: str = "%A, %b %d") -> str:
    """'Sunday, Oct 11' for '2026-10-11'."""
    return datetime.fromisoformat(key).strftime(fmt).replace(" 0", " ")


def ago(key: str, now: float | None = None) -> tuple[float, float]:
    """(midday of that day, now as a day sees it) for components.when: at 00:30 the evening
    that's still going is 'today', not 'yesterday'."""
    now = time.time() if now is None else now
    return datetime.fromisoformat(key).replace(hour=12).timestamp(), now - CUT_H * 3600


def length(seconds: float) -> str:
    """'27 min', '1 h 05 min'."""
    minutes = max(0, int(seconds // 60))
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"


def end_of(match) -> float:
    """When a match was over: its end, else its last yap, else its start; never before its
    start (chat from before a match can join it, #307)."""
    return max(match.started_at, match.ended_at or match.last_yap or match.started_at)


def blocks(matches: Sequence) -> list[tuple[float, list]]:
    """Matches in play order, split where a break of BREAK_S or more came between them:
    (the break before the block in seconds, 0 for the first; its matches)."""
    out: list[tuple[float, list]] = []
    end: float | None = None
    for match in matches:
        pause = 0.0 if end is None else match.started_at - end
        if end is None or pause >= BREAK_S:
            out.append((pause, []))
        out[-1][1].append(match)
        end = end_of(match) if end is None else max(end, end_of(match))
    return out


@dataclass(frozen=True)
class Day:
    key: str  # '2026-10-11'
    matches: tuple  # its MatchRows in play order

    @property
    def started_at(self) -> float:
        return self.matches[0].started_at

    @property
    def ended_at(self) -> float:
        return max(end_of(m) for m in self.matches)

    @property
    def played_s(self) -> float:
        """The play blocks added up, breaks left out."""
        return sum(max(end_of(m) for m in b) - b[0].started_at for _, b in blocks(self.matches))

    @property
    def yaps(self) -> int:
        return sum(m.yaps for m in self.matches)


def group(matches: Sequence) -> list[Day]:
    """Matches in play order -> the days they were played, newest first."""
    by_day: dict[str, list] = {}
    for match in matches:
        by_day.setdefault(match.day or day_of(match.started_at), []).append(match)
    return [Day(key, tuple(rows)) for key, rows in sorted(by_day.items(), reverse=True)]

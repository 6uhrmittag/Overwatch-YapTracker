"""Slow views say so in the log (#387), so the next slow one is a number, not a feeling:

ui: settings took 840 ms (stats 12, pictures 620, debug 190)

From VERY_SLOW_MS on, the line also tells working from waiting (#562): a render that took 50 s on
the clock while YapTracker waited for a core (a match is running, the game goes first) is not a
slow view. "Working" is the CPU time of the thread that builds the view; the rest of the clock
time it waited, for a core or for the disk. The three parts that worked most are named, in CPU
time too (clock time would only say where the waiting happened to land):

ui: live took 51913 ms, 240 ms of it working (chat lines 120, layout 60, status 30)
"""

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

log = logging.getLogger(__name__)

SLOW_MS = 150
VERY_SLOW_MS = 1000
# This render's measured parts: [ms on the clock, ms of CPU]; renders run one at a time.
_parts: dict[str, list[float]] = {}
_lap_at: tuple[float, float] | None = None  # where the next lap() starts; None outside a view


def _now() -> tuple[float, float]:
    return time.perf_counter(), time.thread_time()


def _add(name: str, since: tuple[float, float], now: tuple[float, float]) -> None:
    spent = _parts.setdefault(name, [0.0, 0.0])
    spent[0] += 1000 * (now[0] - since[0])
    spent[1] += 1000 * (now[1] - since[1])


@contextmanager
def part(name: str) -> Iterator[None]:
    """A part of a view worth naming when the view is slow."""
    started = _now()
    try:
        yield
    finally:
        _add(name, started, _now())


def lap(name: str) -> None:
    """Everything since the view began, or since the last lap, was `name`: for views built as one
    long stretch. Outside a render (a timer's refresh) it does nothing."""
    global _lap_at
    if _lap_at is None:
        return
    now = _now()
    _add(name, _lap_at, now)
    _lap_at = now


def line(name: str, took: float, worked: float, parts: dict[str, list[float]]) -> str:
    """The log line for one render: `took` on the clock, `worked` of it on the CPU (ms);
    `parts`: name -> [clock ms, CPU ms]."""
    if took < VERY_SLOW_MS:
        said = ", ".join(f"{n} {ms[0]:.0f}" for n, ms in parts.items())
        return f"ui: {name} took {took:.0f} ms" + (f" ({said})" if said else "")
    top = sorted(parts.items(), key=lambda item: -item[1][1])[:3]
    said = ", ".join(f"{n} {ms[1]:.0f}" for n, ms in top)
    return (f"ui: {name} took {took:.0f} ms, {worked:.0f} ms of it working"
            + (f" ({said})" if said else ""))  # fmt: skip


@contextmanager
def view(name: str) -> Iterator[None]:
    """One render of a view; a line in the log when it took SLOW_MS or longer."""
    global _lap_at
    _parts.clear()
    started = _lap_at = _now()
    try:
        yield
    finally:
        now = _now()
        parts = dict(_parts)
        _parts.clear()
        _lap_at = None
        took = 1000 * (now[0] - started[0])
        if took >= SLOW_MS:
            log.info("%s", line(name, took, 1000 * (now[1] - started[1]), parts))

"""Slow views say so in the log (#387), so the next slow one is a number, not a feeling:

ui: settings took 1240 ms (stats 12, pictures 820, debug 390)

From VERY_SLOW_MS on, the line also tells working from waiting (#562): a render that took 50 s on
the clock while YapTracker waited for a core (a match is running, the game goes first) is not a
slow view. Its three biggest parts are named:

ui: live took 51913 ms, 240 ms of it working (chat lines 120, layout 60, status 30)
"""

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

log = logging.getLogger(__name__)

SLOW_MS = 150
VERY_SLOW_MS = 1000
_parts: dict[str, float] = {}  # this render's measured parts; renders run one at a time
_lap_at: float | None = None  # where the next lap() starts; None outside a view


@contextmanager
def part(name: str) -> Iterator[None]:
    """A part of a view worth naming when the view is slow."""
    started = time.perf_counter()
    try:
        yield
    finally:
        _parts[name] = _parts.get(name, 0.0) + 1000 * (time.perf_counter() - started)


def lap(name: str) -> None:
    """Everything since the view began, or since the last lap, was `name`: for views built as one
    long stretch. Outside a render (a timer's refresh) it does nothing."""
    global _lap_at
    if _lap_at is None:
        return
    now = time.perf_counter()
    _parts[name] = _parts.get(name, 0.0) + 1000 * (now - _lap_at)
    _lap_at = now


def line(name: str, took: float, worked: float, parts: dict[str, float]) -> str:
    """The log line for one render: `took` on the clock, `worked` of it on the CPU (ms)."""
    if took < VERY_SLOW_MS:
        said = ", ".join(f"{n} {ms:.0f}" for n, ms in parts.items())
        return f"ui: {name} took {took:.0f} ms" + (f" ({said})" if said else "")
    top = sorted(parts.items(), key=lambda item: -item[1])[:3]
    said = ", ".join(f"{n} {ms:.0f}" for n, ms in top)
    return (f"ui: {name} took {took:.0f} ms, {worked:.0f} ms of it working"
            + (f" ({said})" if said else ""))  # fmt: skip


@contextmanager
def view(name: str) -> Iterator[None]:
    """One render of a view; a line in the log when it took SLOW_MS or longer."""
    global _lap_at
    _parts.clear()
    started, started_cpu = time.perf_counter(), time.thread_time()
    _lap_at = started
    try:
        yield
    finally:
        took = 1000 * (time.perf_counter() - started)
        worked = 1000 * (time.thread_time() - started_cpu)
        parts = dict(_parts)
        _parts.clear()
        _lap_at = None
        if took >= SLOW_MS:
            log.info("%s", line(name, took, worked, parts))

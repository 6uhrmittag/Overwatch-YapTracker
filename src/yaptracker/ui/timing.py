"""Slow views say so in the log (#387), so the next slow one is a number, not a feeling:

ui: settings took 1240 ms (stats 12, pictures 820, debug 390)
"""

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

log = logging.getLogger(__name__)

SLOW_MS = 150
_parts: dict[str, float] = {}  # this render's measured parts; renders run one at a time


@contextmanager
def part(name: str) -> Iterator[None]:
    """A part of a view worth naming when the view is slow."""
    started = time.perf_counter()
    try:
        yield
    finally:
        _parts[name] = _parts.get(name, 0.0) + 1000 * (time.perf_counter() - started)


@contextmanager
def view(name: str) -> Iterator[None]:
    """One render of a view; a line in the log when it took SLOW_MS or longer."""
    _parts.clear()
    started = time.perf_counter()
    try:
        yield
    finally:
        took = 1000 * (time.perf_counter() - started)
        parts = ", ".join(f"{n} {ms:.0f}" for n, ms in _parts.items())
        _parts.clear()
        if took >= SLOW_MS:
            log.info("ui: %s took %.0f ms%s", name, took, f" ({parts})" if parts else "")

"""Side work next to reading chat (#452): line pictures, debug samples. When it fails (a full
disk, a busy file), the chat line is still stored; the log says so at most once a minute per
kind, with the number of failures in between."""

import logging
import math
import threading
import time
from collections import Counter

log = logging.getLogger(__name__)

EVERY_S = 60.0

_lock = threading.Lock()
_last: dict[str, float] = {}
_skipped: Counter = Counter()


def failed(kind: str, error: BaseException, clock=time.monotonic,
           then: str = "the chat line is kept") -> None:  # fmt: skip
    """Never raises: the caller goes on (with the chat line, or as `then` says)."""
    now = clock()
    with _lock:
        if now - _last.get(kind, -math.inf) < EVERY_S:
            _skipped[kind] += 1
            return
        _last[kind] = now
        skipped = _skipped.pop(kind, 0)
    more = f" ({skipped} more since the last note)" if skipped else ""
    log.warning("%s failed, %s: %s%s", kind, then, error, more, exc_info=error)


def reset() -> None:
    """For tests: every kind may be logged again."""
    with _lock:
        _last.clear()
        _skipped.clear()

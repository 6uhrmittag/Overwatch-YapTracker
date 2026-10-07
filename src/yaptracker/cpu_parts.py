"""Where the app's CPU goes (#302, part of #115). Each part adds the CPU time of the thread it
runs on; once a minute one line in the log gives every part's share of one core, the rest
(UI, the database, the capture copy Windows makes before our callback...) and the whole app:

    cpu parts (in match): reading 16.3 %, change detection 9.8 %, match signals 2.1 %,
    debug samples 3.0 %, capture 3.5 % - rest 4.0 % (whole app 38.7 %)

The state in brackets (#351): in match, between matches, paused or no game (Overwatch isn't
captured). A minute that crossed states names each, "between matches + in match".
"""

import contextlib
import logging
import threading
import time
from collections.abc import Callable, Iterator

log = logging.getLogger(__name__)
PARTS = ("reading", "change detection", "match signals", "debug samples", "capture")


class CpuParts:
    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 cpu: Callable[[], float] = time.process_time,
                 log_every_s: float = 60.0) -> None:  # fmt: skip
        self._clock, self._cpu, self._every = clock, cpu, log_every_s
        self._lock = threading.Lock()
        self._spent = dict.fromkeys(PARTS, 0.0)
        self._states: list[str] = []  # the states seen this minute, in order
        self.state: Callable[[], str] = lambda: ""  # set by the app (#351)
        self._since: float | None = None
        self._cpu_since = 0.0

    def add(self, part: str, seconds: float) -> None:
        with self._lock:
            self._spent[part] += max(0.0, seconds)
        self.tick()

    @contextlib.contextmanager
    def part(self, name: str) -> Iterator[None]:
        """`with CPU.part("change detection"): ...` - this thread's CPU time goes to it."""
        started = time.thread_time()
        try:
            yield
        finally:
            self.add(name, time.thread_time() - started)

    def tick(self) -> None:
        """Logs the line once a minute; cheap otherwise. Called by every add."""
        now, state = self._clock(), self.state()
        with self._lock:
            if state and state not in self._states:
                self._states.append(state)
            if self._since is None:
                self._since, self._cpu_since = now, self._cpu()
                return
            wall = now - self._since
            if wall < self._every:
                return
            whole = self._cpu() - self._cpu_since
            spent, self._spent = self._spent, dict.fromkeys(PARTS, 0.0)
            states, self._states = self._states, [state] if state else []
            self._since, self._cpu_since = now, self._cpu()
        parts = ", ".join(f"{p} {100 * s / wall:.1f} %" for p, s in spent.items())
        rest = max(0.0, whole - sum(spent.values()))
        label = f" ({' + '.join(states)})" if states else ""
        log.info("cpu parts%s: %s - rest %.1f %% (whole app %.1f %%)", label, parts,
                 100 * rest / wall, 100 * whole / wall)  # fmt: skip


CPU = CpuParts()

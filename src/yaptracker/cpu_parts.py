"""Where the app's CPU goes (#302, part of #115). Each part adds the CPU time of the thread it
runs on; once a minute one line in the log gives every part's share of one core, the rest
(UI, the database, the capture copy Windows makes before our callback...) and the whole app:

    cpu parts (in match): reading 16.3 %, change detection 9.8 %, match signals 2.1 %,
    debug samples 3.0 %, capture 3.5 % - rest 4.0 % (whole app 38.7 %)

The state in brackets (#351): in match, between matches, paused or no game (Overwatch isn't
captured). A minute that crossed states names each, "between matches + in match".

A second line splits the minute by thread (#350), because "rest" is where the time between
matches goes and no part says why: every Python thread by name, every other thread of the
process (the capture library, OCR's runtime, the window bridge) as "native":

    cpu threads (between matches): capture watcher 9.8 %, MainThread 4.1 %, native 3.0 %, ...
"""

import contextlib
import logging
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

log = logging.getLogger(__name__)
PARTS = ("reading", "change detection", "match signals", "debug samples", "capture")


class CpuParts:
    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 cpu: Callable[[], float] = time.process_time,
                 log_every_s: float = 60.0,
                 threads: Callable[[], dict[int, float]] | None = None) -> None:  # fmt: skip
        self._clock, self._cpu, self._every = clock, cpu, log_every_s
        self._lock = threading.Lock()
        self._spent = dict.fromkeys(PARTS, 0.0)
        self._states: list[str] = []  # the states seen this minute, in order
        self.state: Callable[[], str] = lambda: ""  # set by the app (#351)
        self._since: float | None = None
        self._cpu_since = 0.0
        self._threads = threads or thread_seconds  # per thread, for the second line (#350)
        self._threads_since: dict[int, float] = {}

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
                self._threads_since = self._read_threads()
                return
            wall = now - self._since
            if wall < self._every:
                return
            whole = self._cpu() - self._cpu_since
            spent, self._spent = self._spent, dict.fromkeys(PARTS, 0.0)
            states, self._states = self._states, [state] if state else []
            self._since, self._cpu_since = now, self._cpu()
            before, self._threads_since = self._threads_since, self._read_threads()
        parts = ", ".join(f"{p} {100 * s / wall:.1f} %" for p, s in spent.items())
        rest = max(0.0, whole - sum(spent.values()))
        label = f" ({' + '.join(states)})" if states else ""
        log.info("cpu parts%s: %s - rest %.1f %% (whole app %.1f %%)", label, parts,
                 100 * rest / wall, 100 * whole / wall)  # fmt: skip
        if threads := by_thread(before, self._threads_since, wall):
            log.info("cpu threads%s: %s", label, threads)

    def _read_threads(self) -> dict[int, float]:
        try:
            return self._threads()
        except Exception:  # a measurement must never break the app
            log.debug("thread CPU times unavailable", exc_info=True)
            return {}


def by_thread(before: dict[int, float], after: dict[int, float], wall: float) -> str:
    """ "capture watcher 9.8 %, MainThread 4.1 %, native 3.0 %": each thread's share of one
    core in the minute, numbered names grouped (ThreadPoolExecutor-0_1), under 0.5 % left out."""
    names = {t.native_id: _family(t.name) for t in threading.enumerate()}
    shares: dict[str, float] = {}
    for tid, seconds in after.items():
        name = names.get(tid, "native")
        shares[name] = shares.get(name, 0.0) + 100 * (seconds - before.get(tid, 0.0)) / wall
    shown = sorted(((s, n) for n, s in shares.items() if s >= 0.5), reverse=True)
    return ", ".join(f"{n} {s:.1f} %" for s, n in shown)


def _family(name: str) -> str:
    return re.sub(r"[-_ ]?\d[\d_]*( \(.*\))?$", "", name) or name


def thread_seconds() -> dict[int, float]:
    """CPU seconds so far of every thread of this process, by native thread id."""
    return _windows_threads() if sys.platform == "win32" else _proc_threads()


def _proc_threads() -> dict[int, float]:
    tick, found = os.sysconf("SC_CLK_TCK"), {}
    for task in Path("/proc/self/task").iterdir():
        try:  # after "(comm)": state, ..., utime and stime are the 12th and 13th
            fields = (task / "stat").read_text().rsplit(")", 1)[1].split()
        except OSError:  # the thread just ended
            continue
        found[int(task.name)] = (int(fields[11]) + int(fields[12])) / tick
    return found


def _windows_threads() -> dict[int, float]:
    import ctypes
    from ctypes import wintypes

    class ThreadEntry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD),
                    ("thread", wintypes.DWORD), ("process", wintypes.DWORD),
                    ("base", wintypes.LONG), ("delta", wintypes.LONG),
                    ("flags", wintypes.DWORD)]  # fmt: skip

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.OpenThread.restype = wintypes.HANDLE
    snapshot = k32.CreateToolhelp32Snapshot(0x4, 0)  # TH32CS_SNAPTHREAD: every thread
    if snapshot in (None, wintypes.HANDLE(-1).value):
        return {}
    found, pid = {}, os.getpid()
    entry = ThreadEntry(size=ctypes.sizeof(ThreadEntry))
    try:
        more = k32.Thread32First(snapshot, ctypes.byref(entry))
        while more:
            if entry.process == pid:
                handle = k32.OpenThread(0x0800, False, entry.thread)  # QUERY_LIMITED_INFO
                if handle:
                    times = [wintypes.FILETIME() for _ in range(4)]
                    if k32.GetThreadTimes(handle, *map(ctypes.byref, times)):
                        kernel, user = times[2], times[3]
                        found[entry.thread] = sum(
                            (t.dwHighDateTime << 32 | t.dwLowDateTime) / 1e7 for t in (kernel, user)
                        )
                    k32.CloseHandle(handle)
            more = k32.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snapshot)
    return found


CPU = CpuParts()

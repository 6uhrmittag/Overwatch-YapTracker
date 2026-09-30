"""Sessions and matches split themselves (#21). No key press needed in a normal evening.

- A **session** is an evening: a new one starts after >= 30 min without capture (also across
  app restarts - the newest session continues if it was active recently).
- A **match** starts with the first chat change of a session, and again when chat comes back
  after >= 5 min of silence (source 'gap'). Ctrl+Alt+M forces one ('hotkey'). The screen
  signals (hero select #93, end screens #94) call start_match / end_match directly.
- Every match start ends a pause (#20).
"""

import threading
import time
from collections.abc import Callable

from yaptracker.pause import Pause
from yaptracker.store.repo import Store

SESSION_GAP_S = 30 * 60
QUIET_GAP_S = 5 * 60


class MatchTracker:
    def __init__(self, store: Store, pause: Pause, clock: Callable[[], float] = time.time) -> None:
        self._store, self._pause, self._clock = store, pause, clock
        self._lock = threading.Lock()  # capture thread, hotkey thread and UI all call in
        self.session_id: int | None = None
        self.match_id: int | None = None
        self.match_started_at: float | None = None
        self._last_alive: float | None = None
        self._last_chat: float | None = None
        # After a restart, the newest session continues if it was active less than 30 min ago.
        self._resumable = store.latest_session()

    def capture_alive(self, ts: float | None = None) -> None:
        """Called for every captured frame, paused or not: the evening is still going."""
        ts = self._clock() if ts is None else ts
        with self._lock:
            if self.session_id is None:
                if self._resumable and ts - self._resumable[1] < SESSION_GAP_S:
                    self.session_id = self._resumable[0]
                    self._store.reopen_session(self.session_id)
                else:
                    self._new_session(ts)
                self._resumable = None
            elif ts - self._last_alive >= SESSION_GAP_S:
                self._new_session(ts)
            self._last_alive = ts

    def chat_changed(self, ts: float | None = None) -> None:
        """New chat text appeared (#17)."""
        ts = self._clock() if ts is None else ts
        with self._lock:
            quiet_for = ts - self._last_chat if self._last_chat is not None else None
            if self.match_id is None or (quiet_for is not None and quiet_for >= QUIET_GAP_S):
                self._start_match(ts, "gap")
            self._last_chat = ts

    def new_match(self, ts: float | None = None, source: str = "hotkey") -> None:
        """Ctrl+Alt+M, or a screen signal from #93."""
        ts = self._clock() if ts is None else ts
        with self._lock:
            self._start_match(ts, source)

    def end_match(self, ts: float | None = None, outcome: str | None = None) -> None:
        """A screen signal from #94: the match is over."""
        ts = self._clock() if ts is None else ts
        with self._lock:
            if self.match_id is not None:
                self._store.end_match(self.match_id, ts, outcome)
                self.match_id = self.match_started_at = None

    def stop(self) -> None:
        """App shutdown: close what's open at the last moment capture was alive."""
        with self._lock:
            if self._last_alive is not None:
                if self.match_id is not None:
                    self._store.end_match(self.match_id, self._last_alive)
                if self.session_id is not None:
                    self._store.end_session(self.session_id, self._last_alive)

    def status(self) -> tuple[int, int | None, float | None] | None:
        """(session number, match number, match start) for the Live header, or None."""
        with self._lock:
            if self.session_id is None:
                return None
            match_no = self._store.match_number(self.match_id) if self.match_id else None
            return self._store.session_number(self.session_id), match_no, self.match_started_at

    def _new_session(self, ts: float) -> None:
        if self.session_id is not None and self._last_alive is not None:
            if self.match_id is not None:
                self._store.end_match(self.match_id, self._last_alive)
            self._store.end_session(self.session_id, self._last_alive)
        self.session_id = self._store.start_session(ts)
        self.match_id = self.match_started_at = self._last_chat = None

    def _start_match(self, ts: float, source: str) -> None:
        if self.session_id is None:
            self._new_session(ts)
        if self.match_id is not None:
            self._store.end_match(self.match_id, self._last_chat or ts)
        self.match_id = self._store.start_match(self.session_id, ts, source)
        self.match_started_at = ts
        self._pause.next_match_started()

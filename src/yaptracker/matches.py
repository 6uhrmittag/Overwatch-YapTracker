"""Sessions and matches split themselves (#21). No key press needed in a normal evening.

- A **session** is an evening: a new one starts after >= 30 min without capture (also across
  app restarts - the newest session continues if it was active recently).
- A **match** starts with the first chat change of a session, and again when chat comes back
  after >= 5 min of silence (source 'gap'). Hero select (#93) starts one too; the end screens
  (#94) end it with its outcome. A match hero select started isn't split by a quiet chat (#377):
  it ends with its end screen, the next hero select, or 25 min after its start.
- By hand (#269), rarely needed: Start match / End match (Ctrl+Alt+M). A start by hand that
  hero select follows within 3 min is that match; one that never gets a line is dropped when
  it's ended by hand or the next match starts, so pressing twice or early leaves nothing.
- After an end, post-game chat ("gg") still belongs to the match. Chat after >= 90 s of quiet
  is the next match whose hero select was missed (source 'gap'; older matches say 'endscreen').
- YapTracker restarted mid-match (an update): the match its shutdown closed goes on (#275).
- Every match start ends a pause (#20).
- Competitive Escort and Hybrid (#364): each team attacks once, so hero select shows again
  between rounds. Hero select on the same map, with no result yet, is the next round, not a
  new match. Only Competitive has those rounds: a match whose queue wasn't read becomes
  Competitive by its second round. Matches split before that, or missed by the rule, are
  merged at the next start (#371), and so are hero-select matches a quiet chat split (#377).
"""

import logging
import threading
import time
from collections.abc import Callable
from typing import NamedTuple

from yaptracker import game_lists
from yaptracker.pause import Pause
from yaptracker.reading_mode import competitive
from yaptracker.store.repo import Store

log = logging.getLogger(__name__)

SESSION_GAP_S = 30 * 60
QUIET_GAP_S = 5 * 60
# Lobby chat before hero select starts a 'gap' match; hero select within this time takes it
# over instead of leaving an almost empty match behind (#93).
ADOPT_GAP_MATCH_S = 3 * 60
AFTER_END_GAP_S = 90
# A match the chat started that no screen ever confirmed (no hero select, no end screen) and
# whose chat lasted less than this was chat outside a match: the login lines, the Practice Range
# while queueing (#307). Its lines go to the match that follows. Longer: a real one, screens missed.
OUTSIDE_CHAT_S = 3 * 60
# YapTracker restarted mid-match (an update, #275): within this, the match goes on.
RESUME_MATCH_S = 10 * 60
# Hero select between rounds of one match (#364): Competitive Escort and Hybrid. With extra
# rounds a match can take ~20 min; hero select later than this is a new match.
ROUND_MATCH_S = 25 * 60
MIRROR_TYPES = frozenset({"escort", "hybrid"})
# A match hero select started goes on through a quiet chat (#377) up to this long after its
# start: longer than any real match (Marv's longest from hero select to end screen: 17 min).
LONGEST_MATCH_S = 25 * 60


class Status(NamedTuple):
    """What the Live header shows: "Session 3 · Match 5 on Eichenwalde · 7:42 in"."""

    session: int
    match: int | None
    started_at: float | None
    map_name: str | None = None
    ended: bool = False
    outcome: str | None = None  # 'victory' | 'defeat' | 'draw', once the end screen said so
    mode: str | None = None  # from hero select, e.g. "UNRANKED" (#268)
    ended_at: float | None = None


class MatchTracker:
    def __init__(
        self,
        store: Store,
        pause: Pause,
        clock: Callable[[], float] = time.time,
        on_missed_end: Callable[[], None] = lambda: None,
        on_missed_start: Callable[[str], None] = lambda source: None,
        on_session_end: Callable[[int], None] = lambda session: None,
    ) -> None:
        self._store, self._pause, self._clock = store, pause, clock
        self._on_missed_end = on_missed_end  # a new match began, but no end screen was seen (#63)
        self._on_missed_start = on_missed_start  # a match began without its hero select (#170)
        self._on_session_end = on_session_end  # its evening line (#379)
        self._lock = threading.Lock()  # capture thread, hotkey thread and UI all call in
        self.session_id: int | None = None
        self.match_id: int | None = None
        self.previous_match_id: int | None = None  # the match before, in this session (#179)
        self.match_started_at: float | None = None
        self.match_map: str | None = None
        self.match_mode: str | None = None
        self.match_ended_at: float | None = None
        self.match_outcome: str | None = None
        self._match_source: str | None = None
        self._round = 1  # of the running match (#364)
        self._before_hand: tuple | None = None  # where things were before a start by hand
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
                    closed = self._store.match_closed_by_shutdown(self.session_id)
                    self._store.reopen_session(self.session_id)
                    if closed is not None and ts - closed[2] < RESUME_MATCH_S:
                        self._resume(closed, ts)
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
            last, ended = self._last_chat, self.match_ended_at
            if self.match_id is None:
                self._start_match(ts, "gap")
            elif ended is not None:
                if ts - (ended if last is None else max(last, ended)) >= AFTER_END_GAP_S:
                    # chat after a result: hero select was missed, the chat starts it (#275)
                    self._start_match(ts, "gap")
            elif last is not None and ts - max(last, self.match_started_at) >= QUIET_GAP_S:
                # quiet since the match started, not since old chat: hero select can start a
                # match long after the last line of the one before
                too_long = ts - self.match_started_at >= LONGEST_MATCH_S
                if self._match_source != "heroselect" or too_long:
                    self._start_match(ts, "gap")
                else:  # nobody typed for a while in a running match: normal (#377)
                    log.info("match %d: 5 min quiet, but hero select started it and no end was "
                             "seen - same match", self.match_id)  # fmt: skip
            self._last_chat = ts

    def chat_activity(self, ts: float) -> None:
        """The chat box changed in a match read afterwards (#345): nothing is read yet, but a
        match the chat started is a real one once it has chat this long (#307). Never starts
        or ends a match itself."""
        with self._lock:
            if self.running:
                self._last_chat = ts if self._last_chat is None else max(self._last_chat, ts)

    def new_match(
        self,
        ts: float | None = None,
        source: str = "hotkey",
        mode: str | None = None,
        map_name: str | None = None,
    ) -> None:
        """Ctrl+Alt+M, or hero select (#93) with the mode and map it showed."""
        ts = self._clock() if ts is None else ts
        with self._lock:
            if source == "heroselect" and self._next_round(ts, mode, map_name):
                self._start_round(mode, map_name)
            elif source == "heroselect" and self._adoptable(ts):
                log.info("match %d: hero select (%s, %s) takes over its start (%s)",
                         self.match_id, mode, map_name, self._match_source)  # fmt: skip
                by_hand = self._match_source == "hotkey"  # its start was a guess: hero select's
                self._store.set_match_source(self.match_id, source, mode, map_name,
                                             ts if by_hand else None)  # fmt: skip
                self._match_source, self.match_map = source, map_name
                self.match_mode = mode
                if by_hand:
                    self.match_started_at = ts
                self._pause.next_match_started()
            else:
                self._start_match(ts, source, mode, map_name)

    def _next_round(self, ts: float, mode: str | None, map_name: str | None) -> bool:
        """Hero select again while a hero-select match runs without a result (#364): the same
        map is its next round. Map unread: a Competitive Escort or Hybrid match's next round.
        Another map or queue is always a new match: a round never changes either, and the
        game doesn't give you the same map twice in a row."""
        if not (self.running and self._match_source == "heroselect"):
            return False
        if ts - self.match_started_at > ROUND_MATCH_S:
            return False
        if mode and self.match_mode and mode != self.match_mode:
            return False  # another queue: a new match
        if map_name and self.match_map:
            return map_name == self.match_map
        return competitive(mode or self.match_mode) and bool(
            game_lists.map_type(self.match_map or map_name) & MIRROR_TYPES
        )

    def _start_round(self, mode: str | None, map_name: str | None) -> None:
        """The next round of the running match: no new match. A second round on the same map
        only happens in Competitive, so an unread queue becomes Competitive (unless the map
        is known to be another type) and the Competitive reading setting applies at once."""
        self._round += 1
        same_map = map_name is not None and map_name == self.match_map
        log.info("match %d: round %d (%s, no result yet)", self.match_id, self._round,
                 "same map" if same_map else "Competitive Escort/Hybrid")  # fmt: skip
        new_mode, new_map = self.match_mode or mode, self.match_map or map_name
        types = game_lists.map_type(new_map)
        if new_mode is None and same_map and (not types or types & MIRROR_TYPES):
            new_mode = "COMPETITIVE"
            log.info("match %d: Competitive, from a mirror round", self.match_id)
        if (new_mode, new_map) != (self.match_mode, self.match_map):
            self.match_mode, self.match_map = new_mode, new_map
            self._store.set_match_source(self.match_id, "heroselect", new_mode, new_map)

    def learn_info(self, mode: str | None, map_name: str | None) -> None:
        """Hero select's queue or map, read on a later look (#342): the running match gets
        what it didn't have yet. The reading mode follows at once (#331)."""
        with self._lock:
            if not self.running or self._match_source != "heroselect":
                return
            mode, map_name = self.match_mode or mode, self.match_map or map_name
            if (mode, map_name) == (self.match_mode, self.match_map):
                return
            self.match_mode, self.match_map = mode, map_name
            self._store.set_match_source(self.match_id, "heroselect", mode, map_name)
            log.info("match %d: hero select read again: %s, %s", self.match_id, mode, map_name)

    def adoptable(self, ts: float | None = None) -> bool:
        """A match the chat, the end screen or a key press started a moment ago: hero select
        now takes it over instead of starting another one."""
        ts = self._clock() if ts is None else ts
        with self._lock:
            return self._adoptable(ts)

    def _adoptable(self, ts: float) -> bool:
        return (
            self.match_id is not None
            and self._match_source in ("gap", "endscreen", "hotkey")
            and self.match_ended_at is None
            and ts - self.match_started_at <= ADOPT_GAP_MATCH_S
        )

    def toggle(self, ts: float | None = None) -> str:
        """The Start match / End match button and Ctrl+Alt+M (#269): ends the running match,
        otherwise starts one. "ended" or "started"."""
        if self.running:
            self.end_match(ts, by_hand=True)
            return "ended"
        self.new_match(ts)
        return "started"

    @property
    def running(self) -> bool:
        """A match has started and its end screen hasn't shown yet."""
        return self.match_id is not None and self.match_ended_at is None

    def end_match(
        self, ts: float | None = None, outcome: str | None = None, by_hand: bool = False
    ) -> None:
        """The end screen (#94): the match is over. A later call may still bring the outcome."""
        ts = self._clock() if ts is None else ts
        with self._lock:
            if self.match_id is None:
                return
            if by_hand and self.running and self._drop_hand_start():
                return  # started by hand a moment ago, nothing in it: as if never pressed
            if self.match_ended_at is None:
                self.match_ended_at, self.match_outcome = ts, outcome
                self._store.end_match(self.match_id, ts, outcome)
                log.info("match %d ended: %s", self.match_id, outcome or "outcome unknown")
            elif outcome and not self.match_outcome:  # "PLAY OF THE GAME" first, outcome later
                self.match_outcome = outcome
                self._store.end_match(self.match_id, self.match_ended_at, outcome)

    def stop(self) -> None:
        """App shutdown: close what's open at the last moment capture was alive."""
        with self._lock:
            if self._last_alive is not None:
                if self.running:
                    self._store.end_match(self.match_id, self._last_alive)
                if self.session_id is not None:
                    self._store.end_session(self.session_id, self._last_alive)
                    self._on_session_end(self.session_id)

    def status(self) -> Status | None:
        """Where the evening is, for the Live header; None before capture ever started."""
        with self._lock:
            if self.session_id is None:
                return None
            match_no = self._store.match_number(self.match_id) if self.match_id else None
            return Status(self._store.session_number(self.session_id), match_no,
                          self.match_started_at, self.match_map,
                          self.match_ended_at is not None, self.match_outcome,
                          self.match_mode, self.match_ended_at)  # fmt: skip

    def _new_session(self, ts: float) -> None:
        if self.session_id is not None and self._last_alive is not None:
            if self.running:
                self._store.end_match(self.match_id, self._last_alive)
            self._store.end_session(self.session_id, self._last_alive)
            self._on_session_end(self.session_id)
        self.session_id = self._store.start_session(ts)
        self.match_id = self.match_started_at = self.match_map = self._last_chat = None
        self.previous_match_id = self.match_mode = None
        self.match_ended_at = self.match_outcome = None

    def _start_match(
        self, ts: float, source: str, mode: str | None = None, map_name: str | None = None
    ) -> None:
        if self.session_id is None:
            self._new_session(ts)
        outside = None  # a match that was only chat outside a match (#307)
        if self.running and not self._drop_hand_start():
            self.match_ended_at = self._last_chat or ts
            self._store.end_match(self.match_id, self.match_ended_at)
            if source != "hotkey" and self._outside_chat():
                outside = self.match_id
            elif source != "hotkey":
                self._on_missed_end()
        if source == "hotkey":
            self._before_hand = (self.match_id, self.previous_match_id, self.match_started_at,
                                 self.match_map, self.match_mode, self.match_ended_at,
                                 self.match_outcome, self._match_source)  # fmt: skip
        self.previous_match_id = self.match_id  # where lines still on screen belong (#179)
        self.match_id = self._store.start_match(self.session_id, ts, source, mode, map_name)
        log.info("match %d started (%s, %s, %s)", self.match_id, source, mode, map_name)
        if outside is not None:
            moved = self._store.move_lines(outside, self.match_id)
            self.previous_match_id = self.match_id  # its lines still on screen, too
            log.info("match %d was chat outside a match (no hero select, no end screen): its "
                     "%d line(s) go to match %d", outside, moved, self.match_id)  # fmt: skip
        self.match_started_at, self.match_map, self._match_source = ts, map_name, source
        self.match_mode, self.match_ended_at, self.match_outcome = mode, None, None
        self._round = 1
        self._pause.next_match_started()
        if source != "heroselect":
            self._on_missed_start(source)

    def _outside_chat(self) -> bool:
        """The running match: started by chat, never confirmed by a screen, not hearted, and its
        chat lasted less than OUTSIDE_CHAT_S (#307)."""
        return (
            self._match_source == "gap"
            and (self._last_chat or self.match_started_at) - self.match_started_at < OUTSIDE_CHAT_S
            and not self._store.loved(self.match_id)
        )

    def _drop_hand_start(self) -> bool:
        """The running match was started by hand and never got a line: remove it and go back
        to where things were (#269). False for any other match, or one with lines."""
        if self._match_source != "hotkey" or self._before_hand is None:
            return False
        if not self._store.drop_match(self.match_id):
            return False
        log.info("match %d dropped: started by hand, nothing in it", self.match_id)
        (self.match_id, self.previous_match_id, self.match_started_at, self.match_map,
         self.match_mode, self.match_ended_at, self.match_outcome,
         self._match_source) = self._before_hand  # fmt: skip
        return True

    def _resume(self, closed: tuple, ts: float) -> None:
        """The match YapTracker's own shutdown closed goes on after a quick restart (#275):
        before, the next chat started a second match inside the same game."""
        self.match_id, self.match_started_at, ended, self.match_map, self.match_mode = closed[:5]
        self._match_source = closed[5]
        self._store.reopen_match(self.match_id)
        log.info("match %d goes on: YapTracker was away %d s", self.match_id, ts - ended)


def merge_split_matches(store: Store, keep: set[int], backup: Callable[[], object]) -> int:
    """At start: one match split in two becomes one again. Never the newest match (it may go
    on, #275), nor one whose chat frames still wait to be read (#349, `keep`). `backup` runs
    before the first merge. The number of merges.

    - A Competitive side swap (#371): two matches in a row on the same map, the first without a
      result (before #364, or missed by its rule). Never two different queues that were both read.
    - A quiet chat (#377, before its fix): the chat started a match 5+ min after the last line of
      a hero-select match that had no end and was still running."""
    merged = 0
    while True:
        pair = _split_pair(store, keep)
        if pair is None:
            return merged
        if not merged:
            log.info("database backed up to %s before merging split matches", backup())
        first, second, mode, why = pair
        moved = store.merge_matches(first, second, mode)
        merged += 1
        log.info("merged match %d into %d: %s (%d lines moved)", second, first, why, moved)


def _split_pair(store: Store, keep: set[int]) -> tuple | None:
    """The oldest match split in two: (first, second, mode after the merge, why), or None."""
    newest = store.newest_match()

    def free(first: int, second: int) -> bool:
        return newest not in (first, second) and not keep & {first, second}

    for first, second, map_name, mode_a, mode_b in store.same_map_pairs(ROUND_MATCH_S):
        if free(first, second) and not (mode_a and mode_b and mode_a != mode_b):
            mode, types = mode_a or mode_b, game_lists.map_type(map_name)
            if mode is None and (not types or types & MIRROR_TYPES):
                mode = "COMPETITIVE"  # only Competitive has rounds with a hero select between
            return first, second, mode, f"mirror round on {map_name}"
    for first, second, mode in store.quiet_split_pairs(LONGEST_MATCH_S, QUIET_GAP_S):
        if free(first, second):
            return first, second, mode, "split by a quiet chat, no end in between"
    return None

"""A starved app isn't a stalled window (#601): in a match the game takes the cores, our threads
wait (#563), and the watchdog's tick comes seconds late. The picture's age says nothing then:
the capture isn't restarted for it, and the chat reader reads less often for a minute."""

import logging

from yaptracker import reader as reader_module
from yaptracker.capture.watcher import (
    STARVED_FOR_S,
    STARVED_STALL_S,
    TICK_S,
    CaptureWatcher,
)

STALL = 3.0


class Source:
    def __init__(self, last_frame_at: float) -> None:
        self.last_frame_at, self.closed = last_frame_at, False

    def close(self) -> None:
        self.closed = True


def watching(now: list[float]) -> tuple[CaptureWatcher, Source]:
    """A watcher mid-capture whose watchdog is driven by hand: tick(seconds since the last)."""
    watcher = CaptureWatcher(lambda: 1, lambda _: None, clock=lambda: now[0],
                             stall_s=lambda: STALL)  # fmt: skip
    watcher._source = source = Source(now[0])
    watcher._opened_at, watcher._due = now[0], now[0] + TICK_S
    return watcher, source


def tick(watcher: CaptureWatcher, now: list[float], after: float = TICK_S) -> None:
    now[0] += after
    watcher._tick(now[0])


def test_a_real_stall_is_still_noticed_after_three_seconds():
    now = [100.0]
    watcher, source = watching(now)
    for _ in range(6):  # 3.0 s without a picture, every tick on time
        tick(watcher, now)
    assert not source.closed
    tick(watcher, now)
    assert source.closed and watcher._stalled[1] == "no picture from the window for 3 s"
    assert not watcher.starved()


def test_a_late_tick_is_not_a_stall_and_says_so(caplog):
    now = [100.0]
    watcher, source = watching(now)
    with caplog.at_level(logging.INFO, logger="yaptracker.capture.watcher"):
        tick(watcher, now, after=8.0)  # the app didn't run for 7.5 s: no picture noted either
    assert not source.closed and watcher._stalled is None
    assert "watchdog tick 7.5 s late" in caplog.text  # still counted per match hour (#563)
    assert "app starved 7.5 s: no picture for 8.0 s isn't taken for a stall" in caplog.text
    assert watcher.starved()


def test_after_a_late_tick_the_stall_clock_starts_again():
    """The picture time is as stale as the tick was late: the next on-time tick mustn't fire."""
    now = [100.0]
    watcher, source = watching(now)
    tick(watcher, now, after=8.0)
    for _ in range(6):  # on time again, still no picture: 3.0 s since the app ran again
        tick(watcher, now)
    assert not source.closed
    tick(watcher, now)  # a real stall: one limit after the starvation ended
    assert source.closed


def test_pictures_after_a_late_tick_keep_the_capture():
    now = [100.0]
    watcher, source = watching(now)
    tick(watcher, now, after=8.0)
    for _ in range(20):
        source.last_frame_at = now[0]
        tick(watcher, now)
    assert not source.closed


def test_a_tick_a_little_late_is_not_starved():
    now = [100.0]
    watcher, source = watching(now)
    for _ in range(4):
        tick(watcher, now, after=TICK_S + 0.9)  # 0.9 s late: under the bar, 5.6 s in all
    assert source.closed and not watcher.starved()


def test_no_picture_at_all_for_half_a_minute_is_lost_however_late_the_ticks():
    now = [100.0]
    watcher, source = watching(now)
    while now[0] - 100.0 <= STARVED_STALL_S - 2.0:
        tick(watcher, now, after=2.0)  # every tick starved
    assert not source.closed
    tick(watcher, now, after=2.5)
    assert source.closed and watcher._stalled[1] == "no picture from the window for 30 s"


def test_starved_lasts_a_minute():
    now = [100.0]
    watcher, source = watching(now)
    tick(watcher, now, after=2.0)
    now[0] += STARVED_FOR_S - 1
    assert watcher.starved()
    now[0] += 1
    assert not watcher.starved()


def reader_with(tmp_path, starved: dict, min_gap_s: float, gated: bool = False, keep=None):
    from yaptracker.matches import MatchTracker
    from yaptracker.pause import Pause
    from yaptracker.store.repo import Store

    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    r = reader_module.ChatReader(lambda image: [], store, MatchTracker(store, Pause()),
                                 min_gap_s=min_gap_s, gated=lambda: gated, keep_gap_s=keep,
                                 starved=lambda: starved["now"])  # fmt: skip
    return r, store


def test_a_starved_app_reads_every_3_s_whatever_was_chosen(tmp_path):
    """Best live isn't held back by the CPU gate (#588), but by starvation it is."""
    starved = {"now": False}
    for folder, chosen in (("a", 0.0), ("b", 1.5)):  # "as fast as it can", every 1.5 s
        (tmp_path / folder).mkdir()
        r, store = reader_with(tmp_path / folder, starved, chosen, keep=lambda: 1.5)
        try:
            starved["now"] = False
            assert r.gap_s() == chosen and r._kept_gap_s() == 1.5
            starved["now"] = True
            assert r.gap_s() == 3.0 and r._kept_gap_s() == 3.0
        finally:
            store.close()


def test_the_reading_line_says_it_was_starved_then_goes_back(monkeypatch, tmp_path, caplog):
    now = [1000.0]
    monkeypatch.setattr(reader_module.time, "monotonic", lambda: now[0])
    starved = {"now": True}
    r, store = reader_with(tmp_path, starved, 0.0)
    try:
        with caplog.at_level(logging.INFO, logger="yaptracker.reader"):
            r.gap_s()  # a read was paced while starved...
            starved["now"] = False  # ...even if it's over when the minute's line is written
            now[0] += 61
            r._count(0.1)
            now[0] += 61
            r._count(0.1)
        first, second = (record.getMessage() for record in caplog.records[:2])
        assert first.endswith("reading every 3 s for a minute (the app was starved: late watchdog"
                              " ticks; chosen as fast as it can)")  # fmt: skip
        assert second.endswith("reading as fast as it can (chosen)")
    finally:
        store.close()

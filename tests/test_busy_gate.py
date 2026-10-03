"""Reading less while busy (#249): after a minute above the CPU goal, one read per 3 s."""

import logging

from yaptracker import reader as reader_module


class Clock:
    def __init__(self):
        self.now, self.cpu = 1000.0, 50.0


def test_above_the_cpu_goal_it_reads_every_3_s_for_a_minute(monkeypatch, tmp_path, caplog):
    from yaptracker.matches import MatchTracker
    from yaptracker.pause import Pause
    from yaptracker.store.repo import Store

    clock = Clock()
    monkeypatch.setattr(reader_module.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(reader_module.time, "process_time", lambda: clock.cpu)
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        r = reader_module.ChatReader(lambda image: [], store, MatchTracker(store, Pause()))
        with caplog.at_level(logging.INFO, logger="yaptracker.reader"):
            clock.now += 61
            clock.cpu += 12.2  # 20 % of a core over that minute
            r._count(0.4)
            assert r.busy
            clock.now += 61
            clock.cpu += 3.0  # 5 %
            r._count(0.2)
            assert not r.busy
        assert "reading every 3 s for a minute" in caplog.records[0].getMessage()
    finally:
        store.close()

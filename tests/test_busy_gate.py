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
        said = caplog.records[0].getMessage()
        assert "reading every 3 s for a minute (above the CPU goal; chosen every 1.5 s)" in said
        assert caplog.records[1].getMessage().endswith("reading every 1.5 s (chosen)")
    finally:
        store.close()


def reader_at(tmp_path, gated, min_gap_s=1.5):
    from yaptracker.matches import MatchTracker
    from yaptracker.pause import Pause
    from yaptracker.store.repo import Store

    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    r = reader_module.ChatReader(lambda image: [], store, MatchTracker(store, Pause()),
                                 min_gap_s=min_gap_s, gated=lambda: gated["on"])  # fmt: skip
    return r, store


def test_best_live_by_choice_is_not_held_back_but_the_defaults_are(tmp_path):
    """#588: the gate is for the default choices (light, after); best live keeps its gap."""
    gated = {"on": True}
    r, store = reader_at(tmp_path, gated)
    try:
        r.busy = True
        assert r.gap_s() == 3.0  # light / after the match / between matches
        gated["on"] = False  # the running match is read live with best
        assert r.gap_s() == 1.5
        assert "best live isn't held back" in r._gap_words()
        r.busy = False
        gated["on"] = True
        assert r.gap_s() == 1.5
    finally:
        store.close()


def test_as_fast_as_it_can_has_no_gap(tmp_path):
    gated = {"on": False}
    r, store = reader_at(tmp_path, gated, min_gap_s=0.0)
    try:
        r.busy = True
        assert r.gap_s() == 0.0
        assert r._gap_words().startswith("reading as fast as it can (chosen;")
        gated["on"] = True  # light: the gate still holds it to 3 s when above the goal
        assert r.gap_s() == 3.0
    finally:
        store.close()


def test_the_gate_follows_the_running_match_mode():
    from yaptracker.reading_mode import BEST, LIGHT, ReadingMode

    class Tracker:
        running, match_mode, match_id = True, "QUICK PLAY", 7

    tracker = {"t": Tracker()}
    other = {"mode": BEST}
    reading = ReadingMode(lambda: tracker["t"], lambda: LIGHT, lambda: other["mode"],
                          lambda: "rapidocr")  # fmt: skip
    assert reading.chosen() == BEST
    other["mode"] = LIGHT
    assert reading.chosen() == LIGHT
    tracker["t"] = None
    assert reading.chosen() == "between"  # between matches the defaults' gate applies


def test_kept_frames_in_a_live_match_keep_their_pace_and_the_gate(tmp_path):
    """Review of #588: a backlog from an after-the-match match isn't read back to back."""
    from yaptracker.matches import MatchTracker
    from yaptracker.pause import Pause
    from yaptracker.store.repo import Store

    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        r = reader_module.ChatReader(lambda image: [], store, MatchTracker(store, Pause()),
                                     min_gap_s=0.0, gated=lambda: False,
                                     keep_gap_s=lambda: 1.5)  # fmt: skip
        assert r._kept_gap_s() == 1.5 and r.gap_s() == 0.0
        r.busy = True
        assert r._kept_gap_s() == 3.0 and r.gap_s() == 0.0
    finally:
        store.close()


def test_chosen_every_3_s_says_chosen_also_above_the_goal(tmp_path):
    r, store = reader_at(tmp_path, {"on": True}, min_gap_s=3.0)
    try:
        r.busy = True
        assert r._gap_words() == "reading every 3 s (chosen)"
    finally:
        store.close()

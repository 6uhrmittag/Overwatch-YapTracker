"""Hero select on a bright map, and a restart mid-match (#275): one match per real match.
The 2026-10-02 log, replayed: 18:33 Victory, map vote, hero select on New Junk City read as
"ASSTOL NONRTEAME", 18:46 Defeat; 21:43 hero select, YapTracker restarted, chat 21:47."""

import numpy as np
import pytest

from yaptracker import signals
from yaptracker.matches import RESUME_MATCH_S, MatchTracker
from yaptracker.pause import Pause
from yaptracker.signals import HeroSelect, is_banner
from yaptracker.store.repo import Store

T0 = 1_000_000.0


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def matches(store):
    return store._read("SELECT source, map, outcome FROM matches ORDER BY id")


@pytest.mark.parametrize("read", ["ASSTOL NONRTEAME", "ASSEMBLE YOUR TEAM", "OMBLEYOUR TEAM"])
def test_the_banner_counts_even_washed_out(read):
    assert is_banner(read)


@pytest.mark.parametrize("read", ["ASPIRANT HACKERS", "ABC LOADOUTFHLTER I）", "COIDO ODVENTUDE",
                                  "COMDETITIVEDDIVL", "A", "TEAM"])  # fmt: skip
def test_other_text_at_that_spot_never_does(read):
    assert not is_banner(read)


def test_hero_select_after_the_map_vote_starts_the_match_not_the_chat(store, monkeypatch):
    monkeypatch.setattr(signals, "has_bright_text", lambda img, **_: True)
    clock = [T0]
    tracker = MatchTracker(store, Pause(), clock=lambda: clock[0])
    tracker.capture_alive(T0)
    tracker.new_match(T0, source="heroselect", map_name="ESPERANCA")
    tracker.chat_changed(T0 + 60)
    tracker.end_match(T0 + 600, outcome="victory")  # 18:33:32
    read = {"text": "VOTE FOR A MAP"}
    hero_select = HeroSelect(lambda img: read["text"],
                             lambda img: ["UNRANKED", "ATTACK", "NEW JUNK CITY · ARENA"],
                             lambda mode, map_name: tracker.new_match(
                                 clock[0], source="heroselect", mode=mode, map_name=map_name),
                             lambda: clock[0])  # fmt: skip
    strip = {"heroselect": np.zeros((90, 1170, 3), np.uint8),
             "heroselect_info": np.zeros((360, 1170, 3), np.uint8)}  # fmt: skip
    for t in range(780, 872, 1):  # menu, map vote, then hero select from 18:38:04
        clock[0] = T0 + t
        tracker.capture_alive(clock[0])
        read["text"] = "ASSTOL NONRTEAME" if t >= 872 - 10 else "VOTE FOR A MAP"
        hero_select.update(strip)
    tracker.chat_changed(T0 + 881)  # 18:38:13: before, this chat started the match
    tracker.end_match(T0 + 1384, outcome="defeat")  # 18:46:36
    assert [(m[0], m[2]) for m in matches(store)] == [("heroselect", "victory"),
                                                      ("heroselect", "defeat")]  # fmt: skip


def test_a_restart_mid_match_goes_on_with_the_same_match(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    tracker.new_match(T0, source="heroselect", map_name="PARAÍSO")  # 21:43:56
    tracker.capture_alive(T0 + 1)
    tracker.stop()  # 21:43:57: YapTracker closes (an update)
    again = MatchTracker(store, Pause())
    again.capture_alive(T0 + 160)  # 21:46:36: back
    again.chat_changed(T0 + 186)  # 21:47:02: before, this started match 25 (gap)
    again.end_match(T0 + 459, outcome="victory")
    assert matches(store) == [("heroselect", "PARAÍSO", "victory")]


def test_after_a_long_break_or_a_result_the_old_match_stays_closed(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    tracker.new_match(T0, source="heroselect", map_name="NEPAL")
    tracker.capture_alive(T0 + 1)
    tracker.stop()
    later = MatchTracker(store, Pause())
    later.capture_alive(T0 + 1 + RESUME_MATCH_S + 5)  # the match is long over by now
    later.chat_changed(T0 + 1 + RESUME_MATCH_S + 10)
    assert [m[0] for m in matches(store)] == ["heroselect", "gap"]
    later.end_match(T0 + 2000, outcome="victory")
    later.capture_alive(T0 + 2001)
    later.stop()
    after_result = MatchTracker(store, Pause())
    after_result.capture_alive(T0 + 2100)
    after_result.chat_changed(T0 + 2110)
    assert len(matches(store)) == 3  # a won match isn't reopened

"""Sessions and matches split themselves (#21): real store, fake clock."""

import pytest

from yaptracker.matches import AFTER_END_GAP_S, QUIET_GAP_S, SESSION_GAP_S, MatchTracker
from yaptracker.pause import Pause
from yaptracker.store.repo import Store

T0 = 1_000_000.0


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def play(tracker, start, seconds, chat_every=None):
    """Capture runs for `seconds`; optionally new chat every `chat_every` seconds."""
    for t in range(int(seconds)):
        tracker.capture_alive(start + t)
        if chat_every and t % chat_every == 0:
            tracker.chat_changed(start + t)


def matches(store):
    return store._read("SELECT session_id, started_at, ended_at, source FROM matches ORDER BY id")


def test_first_chat_of_the_evening_starts_session_1_match_1(store):
    tracker = MatchTracker(store, Pause())
    play(tracker, T0, 60)
    assert tracker.status()[:3] == (1, None, None)  # capturing, nobody typed yet
    tracker.chat_changed(T0 + 60)
    assert tracker.status()[:3] == (1, 1, T0 + 60)
    assert [m[3] for m in matches(store)] == ["gap"]


def test_long_silence_then_chat_is_the_next_match(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    tracker.new_match(T0, source="heroselect")  # chat alone would be chat outside a match (#307)
    play(tracker, T0, 120, chat_every=10)
    store.add_message(ts=T0 + 10, channel="match", text="hi", match_id=tracker.match_id)
    play(tracker, T0 + 120, QUIET_GAP_S + 10)  # 5+ minutes: no chat at all
    tracker.chat_changed(T0 + 120 + QUIET_GAP_S + 10)
    first, second = matches(store)
    assert first[2] == T0 + 110  # ended at its last chat change
    assert second[1] == T0 + 120 + QUIET_GAP_S + 10
    assert tracker.status()[:2] == (1, 2)  # empty matches wouldn't count (#270): it has a line


def test_a_normal_chatty_match_is_not_split(store):
    tracker = MatchTracker(store, Pause())
    play(tracker, T0, 20 * 60, chat_every=60)
    assert len(matches(store)) == 1


def test_half_an_hour_without_capture_starts_a_new_session(store):
    tracker = MatchTracker(store, Pause())
    play(tracker, T0, 60, chat_every=30)
    later = T0 + 60 + SESSION_GAP_S
    tracker.capture_alive(later)
    tracker.chat_changed(later)
    assert tracker.status()[:2] == (2, 1)
    sessions = store._read("SELECT started_at, ended_at FROM sessions ORDER BY id")
    assert sessions == [(T0, T0 + 59), (later, None)]


def test_restarting_the_app_continues_a_recent_session(store):
    tracker = MatchTracker(store, Pause())
    play(tracker, T0, 60, chat_every=30)
    tracker.stop()
    again = MatchTracker(store, Pause())
    again.capture_alive(T0 + 600)
    again.chat_changed(T0 + 600)
    assert again.status()[0] == 1  # still session 1, 10 minutes later
    assert store._read("SELECT ended_at FROM sessions") == [(None,)]


def test_ctrl_alt_m_forces_a_new_match_and_ends_a_pause(store):
    pause = Pause()
    tracker = MatchTracker(store, pause)
    play(tracker, T0, 30, chat_every=10)
    pause.pause()
    tracker.new_match(T0 + 30)
    assert not pause.paused
    assert [m[3] for m in matches(store)] == ["gap", "hotkey"]


def test_every_match_start_ends_a_pause(store):
    pause = Pause()
    tracker = MatchTracker(store, pause)
    tracker.capture_alive(T0)
    pause.pause()
    tracker.chat_changed(T0 + 1)
    assert not pause.paused


def test_post_game_chat_stays_with_the_match_until_90_s_of_quiet(store):
    tracker = MatchTracker(store, Pause())
    play(tracker, T0, 30, chat_every=10)
    tracker.end_match(T0 + 30, outcome="victory")
    assert tracker.status()[1:6] == (1, T0, None, True, "victory")
    assert not tracker.running
    tracker.chat_changed(T0 + 40)  # "gg"
    tracker.chat_changed(T0 + 40 + AFTER_END_GAP_S - 1)  # "gg wp", still the same match
    assert len(matches(store)) == 1
    tracker.chat_changed(T0 + 40 + 2 * AFTER_END_GAP_S)  # back in the lobby: the next match
    assert [(m[2], m[3]) for m in matches(store)] == [(T0 + 30, "gap"), (None, "gap")]  # (#275)
    assert store._read("SELECT outcome FROM matches ORDER BY id") == [("victory",), (None,)]
    assert tracker.running


def test_quiet_after_an_end_counts_even_if_nobody_chatted_in_the_match(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    tracker.new_match(T0, source="heroselect")
    tracker.end_match(T0 + 600, outcome="defeat")
    tracker.chat_changed(T0 + 600 + AFTER_END_GAP_S)
    assert [m[3] for m in matches(store)] == ["heroselect", "gap"]  # (#275)


def test_the_outcome_may_come_after_play_of_the_game(store):
    tracker = MatchTracker(store, Pause())
    play(tracker, T0, 30, chat_every=10)
    tracker.end_match(T0 + 30)  # PLAY OF THE GAME: over, outcome unknown
    tracker.end_match(T0 + 45, outcome="defeat")  # "DEFEAT EICHENWALDE"
    tracker.end_match(T0 + 50, outcome="victory")  # never overwrites a known outcome
    assert store._read("SELECT ended_at, outcome FROM matches") == [(T0 + 30, "defeat")]


def test_an_ended_match_keeps_its_end_when_the_next_one_starts(store):
    tracker = MatchTracker(store, Pause())
    play(tracker, T0, 30, chat_every=10)
    tracker.end_match(T0 + 30, outcome="victory")
    tracker.chat_changed(T0 + 60)  # "gg"
    tracker.new_match(T0 + 120, source="heroselect", map_name="EICHENWALDE")
    tracker.capture_alive(T0 + 200)
    tracker.stop()
    assert [(m[2], m[3]) for m in matches(store)] == [(T0 + 30, "gap"), (T0 + 200, "heroselect")]


def test_hero_select_brings_mode_and_map(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    tracker.new_match(T0 + 5, source="heroselect", mode="UNRANKED", map_name="ESPERANCA")
    assert tracker.status().map_name == "ESPERANCA"
    assert store._read("SELECT source, mode, map FROM matches") == [
        ("heroselect", "UNRANKED", "ESPERANCA")
    ]


def test_hero_select_takes_over_a_match_that_lobby_chat_just_started(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    tracker.chat_changed(T0 + 10)  # people chat in the lobby
    tracker.new_match(T0 + 40, source="heroselect", mode="UNRANKED", map_name="ESPERANCA")
    assert store._read("SELECT source, started_at, map FROM matches") == [
        ("heroselect", T0 + 10, "ESPERANCA")
    ]


def test_a_match_the_chat_started_can_be_taken_over_for_three_minutes(store):
    """#300: what the "HERO DETAILS" hint asks before it confirms a start."""
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    assert not tracker.adoptable(T0)  # nothing running
    tracker.chat_changed(T0 + 10)
    assert tracker.adoptable(T0 + 20) and not tracker.adoptable(T0 + 10 + 181)
    tracker.new_match(T0 + 20, source="heroselect", mode="UNRANKED")
    assert not tracker.adoptable(T0 + 30)  # hero select has it now
    assert [m[3] for m in matches(store)] == ["heroselect"]


def test_hero_select_after_a_long_chat_match_is_the_next_match(store):
    tracker = MatchTracker(store, Pause())
    play(tracker, T0, 600, chat_every=30)
    tracker.new_match(T0 + 600, source="heroselect", mode="UNRANKED", map_name="EICHENWALDE")
    assert [m[3] for m in matches(store)] == ["gap", "heroselect"]


def test_hero_select_long_after_the_last_chat_keeps_its_first_chat(store):
    """#181: 20:43 last chat, 20:47 hero select, 20:48 first chat: still the same match."""
    tracker = MatchTracker(store, Pause())
    play(tracker, T0, 60, chat_every=20)  # the match before, chatting
    tracker.end_match(T0 + 60, "victory")
    play(tracker, T0 + 60, 240)  # menu and queue: nobody types
    tracker.new_match(T0 + 300, source="heroselect", mode="UNRANKED", map_name="ESPERANÇA")
    play(tracker, T0 + 300, QUIET_GAP_S - 200)
    tracker.chat_changed(T0 + 300 + 75)  # > 5 min after the last chat, 75 s into the match
    tracker.chat_changed(T0 + QUIET_GAP_S + 200)
    assert [m[3] for m in matches(store)] == ["gap", "heroselect"]


def say(tracker, store, ts, text="Over here!"):
    """A line the reader stores: the tracker hears of it first, then it goes to its match."""
    tracker.chat_changed(ts)
    store.add_message(ts=ts, channel="team", text=text, match_id=tracker.match_id)


def played(store):
    return [(m[0], m[7]) for m in store.all_matches()]  # (id, source) of what Sessions shows


def test_login_lines_before_the_first_match_go_to_it(store):
    """#307, 2026-10-04 11:47: a friend-list line at the login screen started match 59; hero
    select came 3.7 min later (too late to take it over), and logged a missed end."""
    missed = []
    tracker = MatchTracker(store, Pause(), on_missed_end=lambda: missed.append(1))
    tracker.capture_alive(T0)
    say(tracker, store, T0, "[Pal] started playing Overwatch.")
    tracker.new_match(T0 + 220, source="heroselect", mode="UNRANKED")
    (first,) = played(store)
    assert first[1] == "heroselect" and missed == []
    assert [m.text for m in store.messages(first[0])] == ["[Pal] started playing Overwatch."]


def test_practice_range_chat_between_matches_joins_the_next_match(store):
    """#307, 2026-10-04 15:03-15:17: 9 lines in 50 s, 8.5 min later 2 more (the quiet rule split
    them), then hero select. Before: three matches, two of them only Practice Range chat."""
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    tracker.new_match(T0, source="heroselect")
    say(tracker, store, T0 + 60, "gl hf")
    tracker.end_match(T0 + 600, "victory")
    for t in range(0, 50, 6):
        say(tracker, store, T0 + 1110 + t)
    for t in (0, 20):
        say(tracker, store, T0 + 1620 + t)
    tracker.new_match(T0 + 1944, source="heroselect", mode="UNRANKED")
    (before, _), (after, source) = played(store)
    assert source == "heroselect" and len(store.messages(after)) == 11
    assert [m.text for m in store.messages(before)] == ["gl hf"]


def test_a_real_match_whose_screens_were_missed_stays_a_match(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    for t in range(0, 300, 30):  # 4.5 min of chat: a match, no hero select or end screen seen
        say(tracker, store, T0 + t, "push the payload")
    gap = tracker.match_id
    tracker.new_match(T0 + 600, source="heroselect")
    assert played(store) == [(gap, "gap")] and len(store.messages(gap)) == 10


def test_a_hearted_chat_match_stays(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    say(tracker, store, T0, "this lobby is gold")
    gap = tracker.match_id
    store.set_loved(gap, T0 + 5)
    tracker.new_match(T0 + 400, source="heroselect")
    assert played(store) == [(gap, "gap")] and len(store.messages(gap)) == 1

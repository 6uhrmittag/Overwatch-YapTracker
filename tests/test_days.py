"""Sessions by day (#440): a day runs until 05:00, breaks split it into play blocks, and every
match is numbered in its day - in Sessions, Search, the profile and Live alike."""

import time

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, days, runtime
from yaptracker.store.repo import Store
from yaptracker.ui import shell


def at(day: int, hour: int, minute: int = 0) -> float:
    """Local time in October 2026; Sunday is the 11th."""
    return time.mktime((2026, 10, day, hour, minute, 0, 0, 0, -1))


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def played(store, session: int, start: float, minutes: int, text: str = "gg") -> int:
    match = store.start_match(session, start, "heroselect")
    store.add_message(ts=start + 60, channel="match", text=text, match_id=match)
    store.end_match(match, start + minutes * 60, "victory")
    return match


def sunday(store) -> list[int]:
    """Sunday: 15:05 + 15:20, a break, 18:38, then a late evening 23:30 + 00:40 + 04:50
    (after midnight, before 05:00: still Sunday). Monday 05:10 is a new day."""
    afternoon = store.start_session(at(11, 15, 0))
    ids = [
        played(store, afternoon, at(11, 15, 5), 12),
        played(store, afternoon, at(11, 15, 20), 10),
    ]
    evening = store.start_session(at(11, 18, 30))  # 30 min without Overwatch: a new session
    ids.append(played(store, evening, at(11, 18, 38), 15))
    ids += [played(store, evening, at(11, 23, 30), 20), played(store, evening, at(12, 0, 40), 15)]
    ids.append(played(store, evening, at(12, 4, 50), 9))
    ids.append(played(store, store.start_session(at(12, 5, 5)), at(12, 5, 10), 10, "rein pls"))
    return ids


def test_a_day_runs_until_five_in_the_morning():
    assert days.day_of(at(12, 4, 59)) == "2026-10-11"
    assert days.day_of(at(12, 5, 0)) == "2026-10-12"
    assert days.title("2026-10-11") == "Sunday, Oct 11"


def test_days_newest_first_with_play_blocks_and_time_played(store):
    ids = sunday(store)
    monday, sunday_ = days.group(store.played_matches())
    assert (monday.key, [m.id for m in monday.matches]) == ("2026-10-12", ids[6:])  # one match
    assert (monday.played_s, monday.yaps) == (600, 1)
    assert sunday_.key == "2026-10-11" and [m.id for m in sunday_.matches] == ids[:6]
    blocks = days.blocks(sunday_.matches)
    assert [[m.id for m in b] for _, b in blocks] == [
        ids[:2],
        [ids[2]],
        [ids[3]],
        [ids[4]],
        [ids[5]],
    ]
    assert [round(pause / 60) for pause, _ in blocks] == [0, 188, 277, 50, 235]
    # 15:05-15:30 + 18:38-18:53 + 23:30-23:50 + 00:40-00:55 + 04:50-04:59, not 15:05 to 04:59
    assert sunday_.played_s == (25 + 15 + 20 + 15 + 9) * 60
    assert (sunday_.started_at, sunday_.ended_at) == (at(11, 15, 5), at(12, 4, 59))


def test_matches_are_numbered_in_their_day_across_sessions(store):
    ids = sunday(store)
    assert [store.match_number(i) for i in ids] == [1, 2, 3, 4, 5, 6, 1]
    assert [m.id for m in store.played_matches("2026-10-11")] == ids[:6]
    assert store.played_matches("") == [] and store.match_day(ids[5]) == "2026-10-11"
    (hit,) = store.find("rein")
    assert (hit.day, hit.match_number) == ("2026-10-12", 1)  # Monday's first, not a 7th
    assert [h.match_number for h in store.find("gg")] == [6, 5, 4, 3, 2, 1]
    assert store.day_numbers({ids[4]})[ids[1]] == ("2026-10-11", 2)  # the whole day


def test_a_day_is_worked_out_once_so_no_match_falls_between_two(store):
    """Python and SQLite round a moment just before 05:00 differently: the list, the day view
    and the numbers all use the store's day."""
    session = store.start_session(at(11, 22))
    edge = played(store, session, at(12, 5) - 0.0003, 10)
    (day,) = days.group(store.played_matches())
    assert [m.id for m in store.played_matches(day.key)] == [edge]
    assert store.match_day(edge) == day.key


def test_chat_from_before_a_match_never_ends_it_before_it_began(store):
    session = store.start_session(at(11, 19))
    match = store.start_match(session, at(11, 19, 30), "heroselect")
    store.add_message(ts=at(11, 19, 27), channel="match", text="gl", match_id=match)  # #307
    (day,) = days.group(store.played_matches())
    assert (day.ended_at, day.played_s) == (at(11, 19, 30), 0)


def test_the_evening_still_going_after_midnight_is_today():
    from yaptracker.ui.components import when

    assert when(*days.ago("2026-10-11", now=at(12, 0, 30))) == "today"
    assert when(*days.ago("2026-10-11", now=at(12, 6))) == "yesterday"


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_a_day_shows_its_matches_with_breaks(user: User, store, monkeypatch):
    config.save_setup_state("done")
    ids = sunday(store)
    monkeypatch.setattr(runtime, "store", store)
    await user.open("/")
    user.find(marker="nav-sessions").click()
    await user.should_see("Past midnight still counts to the day before, until 5 am.")
    await user.should_see("Monday, Oct 12")
    await user.should_see("15:05–04:59 · 1 h 24 min played · 6 matches · 6 yaps")
    user.find(marker="day-2026-10-11").click()
    await user.should_see("Match 6")
    body = user.find(marker="matches").elements.pop()
    shown = [row.text if "break-line" in row._markers else row._markers[1]
             for row in body.default_slot.children]  # fmt: skip
    assert shown == [f"match-{ids[0]}", f"match-{ids[1]}", "Break, 3 h 08 min",
                     f"match-{ids[2]}", "Break, 4 h 37 min", f"match-{ids[3]}", "Break, 50 min",
                     f"match-{ids[4]}", "Break, 3 h 55 min", f"match-{ids[5]}"]  # fmt: skip
    user.find(marker=f"match-{ids[4]}").click()
    await user.should_see("Match 5")
    user.find(marker="back-to-matches").click()  # back to Sunday, not to a session
    await user.should_see("Match 6")


async def test_a_search_result_opens_its_match_in_its_day(user: User, store, monkeypatch):
    config.save_setup_state("done")
    ids = sunday(store)
    store.add_message(ts=at(12, 0, 45), channel="team", text="wahoo", match_id=ids[4])
    monkeypatch.setattr(runtime, "store", store)
    await user.open("/")
    user.find(marker="nav-search").click()
    user.find(marker="search-box").type("wahoo")
    await user.should_see("Match 5")  # Sunday's 5th, after midnight
    user.find(marker="search-hit").click()
    await user.should_see("All matches")
    user.find(marker="back-to-matches").click()
    await user.should_see("Sunday, Oct 11")

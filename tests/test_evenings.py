"""One quality line per evening (#379): in the log at its end, in Settings -> About."""

import json
import logging
import time

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.evenings import Evenings, line
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.store.repo import Store
from yaptracker.ui import shell

T0 = time.mktime((2026, 10, 10, 20, 0, 0, 0, 0, -1))  # local time, as the log writes it


def clock(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) + ",123"


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


@pytest.fixture
def log_file(tmp_path):
    path = tmp_path / "yaptracker.log"
    path.write_text(
        f"{clock(T0 - 60)} INFO yaptracker.reader: chat reading: 9 frames, 900 ms CPU each "
        "(best 9); whole app: 90.0 % of a core\n"  # before the evening: not counted
        f"{clock(T0 + 60)} INFO yaptracker.reader: chat reading: 16 frames, 1332 ms CPU each "
        "(best 12, after 4); whole app: 20.0 % of a core\n"
        f"{clock(T0 + 120)} INFO yaptracker.reader: chat reading: no chat in the box between "
        "matches, reading every 3 s; 2 changed frames in 60 s\n"
        f"{clock(T0 + 180)} INFO yaptracker.reader: chat reading: 4 frames, 558 ms CPU each; "
        "whole app: 30.0 % of a core\n",
        encoding="utf-8",
    )
    return path


def an_evening(tracker, store):
    """Hero select on a known map, a match the chat started, one started by hand."""
    tracker.capture_alive(T0)
    tracker.new_match(T0, source="heroselect", mode="UNRANKED", map_name="Eichenwalde")
    match = tracker.match_id
    for n, confidence in enumerate((0.99, 0.97, 0.5, 0.98)):
        store.add_message(ts=T0 + 10 + n, channel="match", text=f"yap {n}", match_id=match,
                          ocr_confidence=confidence, has_glyphs=n == 1)  # fmt: skip
    edited = store.messages(match)[0].id
    store.edit_message(edited, "fixed by hand", T0 + 30)
    tracker.end_match(T0 + 100, "victory")
    tracker.chat_changed(T0 + 300)  # hero select missed: the chat starts the next match
    store.add_message(
        ts=T0 + 300, channel="team", text="gg", match_id=tracker.match_id, ocr_confidence=0.99
    )
    tracker.new_match(T0 + 400)  # by hand, never got a line or result: not played
    tracker.capture_alive(T0 + 500)


def test_the_end_of_an_evening_writes_its_line(store, log_file, tmp_path, caplog):
    caplog.set_level(logging.INFO, "yaptracker.evenings")
    evenings = Evenings(tmp_path / "evenings.json", store, lambda since: [log_file])
    tracker = MatchTracker(store, Pause(), on_session_end=evenings.record)
    an_evening(tracker, store)
    tracker.stop()  # YapTracker quits
    assert (
        "evening 2026-10-10: 2 matches (hero select 1, gap 1, hand 0) · map known 100 % · queue "
        "known 100 % · result 50 % · missed ends 1 · lines 5 (avg confidence 0.89, "
        "low-confidence 20 %, ◇ 20 %) · fixed by hand 1 · read modes best 12, light 0, after 4 "
        "· whole app 25 % of a core" in caplog.text
    )
    saved = json.loads((tmp_path / "evenings.json").read_text(encoding="utf-8"))
    assert [e["session"] for e in saved] == [tracker.session_id]
    caplog.clear()
    evenings.record(tracker.session_id)  # Overwatch closed, then the app quit: said once
    assert "evening" not in caplog.text


def test_the_next_evening_ends_the_one_before(store, log_file, tmp_path, caplog):
    caplog.set_level(logging.INFO, "yaptracker.evenings")
    evenings = Evenings(tmp_path / "evenings.json", store, lambda since: [log_file])
    tracker = MatchTracker(store, Pause(), on_session_end=evenings.record)
    an_evening(tracker, store)
    tracker.capture_alive(T0 + 86_400)  # the next day: a new session
    assert "evening 2026-10-10: 2 matches" in caplog.text


def test_evenings_since_october_are_filled_in_once(store, log_file, tmp_path, caplog):
    caplog.set_level(logging.INFO, "yaptracker.evenings")
    september = store.start_session(time.mktime((2026, 9, 30, 20, 0, 0, 0, 0, -1)))
    old = store.start_match(september, T0 - 900_000, "gap", None, None)
    store.add_message(ts=T0 - 900_000, channel="team", text="old", match_id=old)
    tracker = MatchTracker(store, Pause())
    an_evening(tracker, store)
    store.start_session(T0 + 86_400)  # an evening without a played match: no row
    evenings = Evenings(tmp_path / "evenings.json", store, lambda since: [log_file])
    evenings.backfill()
    assert [e["date"] for e in evenings.last()] == ["2026-10-10"]
    assert "(filled in)" in caplog.text
    (tmp_path / "evenings.json").write_text("[]", encoding="utf-8")
    evenings.backfill()  # the file is there: never again
    assert evenings.last() == []


def test_without_matches_or_log_lines_nothing_is_made_up(store, tmp_path):
    evenings = Evenings(tmp_path / "evenings.json", store, lambda since: [])
    tracker = MatchTracker(store, Pause(), on_session_end=evenings.record)
    tracker.capture_alive(T0)
    tracker.chat_changed(T0 + 10)
    store.add_message(ts=T0 + 10, channel="team", text="hi", match_id=tracker.match_id)
    tracker.stop()
    (e,) = evenings.last()
    assert (e["map"], e["queue"], e["modes"], e["cpu"]) == (None, None, None, None)
    assert "map known - · queue known -" in line(e) and "whole app - of a core" in line(e)


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_about_lists_the_last_evenings(user: User, store, log_file, tmp_path, monkeypatch):
    config.save_setup_state("done")
    monkeypatch.setattr(runtime, "evenings", None)
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("After your first evening with Overwatch, a row shows up here")
    evenings = Evenings(tmp_path / "evenings.json", store, lambda since: [log_file])
    tracker = MatchTracker(store, Pause(), on_session_end=evenings.record)
    an_evening(tracker, store)
    tracker.stop()
    monkeypatch.setattr(runtime, "evenings", evenings)
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see(marker="evenings")
    table = user.find(marker="evenings").elements.pop().content
    assert "<td>Sat Oct 10</td><td>2</td><td>100 %</td>" in table

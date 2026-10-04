"""Chat outside a match (#176): menu after a match, map vote. Read from a taller strip."""

import json
import time
from pathlib import Path

import numpy as np
import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.app import capture_region
from yaptracker.capture.changes import text_mask
from yaptracker.capture.source import Region
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import parse
from yaptracker.store.repo import Store
from yaptracker.ui import shell

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "dedup" / "176-outside-match.json")
                     .read_text(encoding="utf-8"))  # fmt: skip


def test_outside_a_match_the_strip_reaches_the_bottom_edge():
    box = Region(55, 510, 615, 395)  # the default box at 1440p
    assert capture_region(box, 1440, match_running=True) == box
    assert capture_region(box, 1440, match_running=False) == Region(55, 510, 615, 930)


def test_the_text_mask_judges_letters_by_the_window_not_the_crop():
    box = np.zeros((395, 615, 3), np.uint8)
    box[100:118, 40:300:12] = (60, 230, 240)  # a row of letter-sized strokes
    tall = np.vstack([box, np.zeros((535, 615, 3), np.uint8)])
    same = text_mask(tall, scale=1.0)[:395]
    assert same.any()  # the strokes count as letters
    assert not text_mask(tall)[:395].any()  # judged by the tall crop they'd be too small
    assert np.array_equal(same, text_mask(box, scale=1.0))
    assert np.array_equal(text_mask(box), text_mask(box, scale=1.0))  # the default box: as before


def lines(screen: str) -> list[OcrLine]:
    return [
        OcrLine(o["text"], o["confidence"], Region(*o["box"])) for o in FIXTURE["screens"][screen]
    ]


def test_the_menu_after_a_match_and_the_map_vote_parse_as_chat():
    menu = [(p.kind, p.speaker, p.text) for p in parse(lines("menu"))]
    assert menu == [
        ("cut", None, "zz -Zxzx! zxzxz"),
        ("message", "MoonPebble", "Perfect team"),
        ("system", None, "You endorsed SturdyHero!"),
        ("system", None, "Endorsement Received!"),
        ("message", "tortillaTank", "<3"),
        ("message", "KindStranger", "I'm sorry you guys suffered for our 20 mins in q"),
        ("system", None, "KindStranger's group wants to stay as a team"),
        ("input", None, "[Group]"),
    ]
    assert [(p.kind, p.text) for p in parse(lines("vote"))] == [("message", "SEEEEEEEEEEEX")]


def shown(row) -> str:
    """What a transcript row says: a chat line's text, or a divider's label."""
    if "chat-line" in row._markers:
        return next(c.content for c in row.descendants() if hasattr(c, "content"))
    return row.text


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_the_transcript_marks_what_was_said_after_the_result(user: User, tmp_path,
                                                                   monkeypatch):  # fmt: skip
    config.save_setup_state("done")
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        now = time.time()
        session = store.start_session(now - 900)
        match = store.start_match(session, now - 900, "heroselect")
        store.add_message(ts=now - 800, channel="match", text="gl hf", speaker_raw="Pickle",
                          match_id=match)  # fmt: skip
        store.end_match(match, now - 300, "victory")
        store.add_message(ts=now - 280, channel="match", text="Perfect team", speaker_raw="Pickle",
                          match_id=match)  # fmt: skip
        monkeypatch.setattr(runtime, "store", store)
        await user.open("/")
        user.find(marker="nav-sessions").click()
        user.find(marker=f"session-{session}").click()
        user.find(marker=f"match-{match}").click()
        await user.should_see("After the match (won)")
        body = user.find(marker="transcript").elements.pop()
        order = [shown(row) for row in body.default_slot.children]
        assert order == ["gl hf", "After the match (won)", "Perfect team"]
    finally:
        store.close()


async def test_chat_before_the_match_comes_first_with_a_minus_time(user: User, tmp_path,
                                                                   monkeypatch):  # fmt: skip
    """#307: Practice Range chat while queueing joins the match after it."""
    config.save_setup_state("done")
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        now = time.time()
        session = store.start_session(now - 1000)
        match = store.start_match(session, now - 900, "heroselect")
        store.add_message(ts=now - 1000, channel="team", text="Over here!", speaker_raw="Pickle",
                          match_id=match)  # fmt: skip
        store.add_message(ts=now - 800, channel="match", text="gl hf", speaker_raw="Pickle",
                          match_id=match)  # fmt: skip
        monkeypatch.setattr(runtime, "store", store)
        await user.open("/")
        user.find(marker="nav-sessions").click()
        user.find(marker=f"session-{session}").click()
        user.find(marker=f"match-{match}").click()
        await user.should_see("The match starts")
        body = user.find(marker="transcript").elements.pop()
        order = [shown(row) for row in body.default_slot.children]
        assert order == ["Over here!", "The match starts", "gl hf"]
        await user.should_see("-1:40")
    finally:
        store.close()

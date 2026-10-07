"""Menus aren't chat (#115): between matches the box reaches into the menu, whose art changes
every frame. After a few reads without a chat line, it's read every 6 s until chat shows up."""

import logging
import threading
import time

import numpy as np
import pytest

from yaptracker import reader as reader_module
from yaptracker.capture.source import Region
from yaptracker.matches import MatchTracker
from yaptracker.ocr.engine import OcrLine
from yaptracker.pause import Pause
from yaptracker.reader import MENU_GAP_S, NO_CHAT_READS, ChatReader
from yaptracker.store.repo import Store

MENU = [OcrLine("The graveyard stirs! Join the madness", 0.99, Region(116, 172, 805, 46)),
        OcrLine("OPEN EVENT PLAY", 0.98, Region(190, 460, 602, 46))]  # fmt: skip
CHAT = [OcrLine("[Pickle]: anyone up for a 6 stack?", 0.99, Region(64, 1300, 600, 30))]


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def test_a_menu_without_chat_is_read_every_6_s_until_chat_shows_up(store, caplog):
    menu, chat = np.zeros((40, 40, 3), np.uint8), np.zeros((40, 40, 3), np.uint8)
    reads = {id(menu): MENU, id(chat): MENU + CHAT}
    running = [False]
    reader = ChatReader(lambda image: reads[id(image)], store, MatchTracker(store, Pause()),
                        idle=lambda: not running[0])  # fmt: skip
    for n in range(NO_CHAT_READS):
        assert not reader.menu
        reader.read_frame(1000.0 + 3 * n, menu)
    assert reader.menu
    running[0] = True
    assert not reader.menu  # in a match: read as usual
    running[0] = False
    reader._load_since -= 61  # a minute has passed: the log says it
    with caplog.at_level(logging.INFO, logger="yaptracker.reader"):
        reader.read_frame(1020.0, menu)
    assert f"no chat in the box between matches, reading every {MENU_GAP_S:g} s" in caplog.text
    reader.read_frame(1026.0, chat)  # someone types: back to normal at once
    assert not reader.menu


def test_the_reader_waits_the_menu_gap_between_reads(store, monkeypatch):
    monkeypatch.setattr(reader_module, "MENU_GAP_S", 0.3)
    image = np.zeros((40, 40, 3), np.uint8)
    times, done = [], threading.Event()

    def read(_):
        times.append(time.monotonic())
        if len(times) == NO_CHAT_READS + 2:
            done.set()
        return MENU

    reader = ChatReader(read, store, MatchTracker(store, Pause()), min_gap_s=0.0)
    reader.start()
    try:
        while not done.is_set():
            reader.offer(image)
            time.sleep(0.01)
    finally:
        reader.stop()
    gaps = np.diff(times)
    assert max(gaps[: NO_CHAT_READS - 1]) < 0.2  # chat-paced until then
    assert min(gaps[NO_CHAT_READS:]) >= 0.29  # then the menu gap

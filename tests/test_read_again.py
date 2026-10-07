"""Read again, best quality (#333): a match's lines or one line, from their saved pictures."""

import time

import numpy as np
import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.capture.source import Region
from yaptracker.lines import LinePictures
from yaptracker.ocr.engine import OcrLine
from yaptracker.read_again import ReadAgain
from yaptracker.store.repo import Store
from yaptracker.ui import shell

T0 = time.mktime((2026, 10, 7, 20, 0, 0, 0, 0, -1))
BOX = Region(0, 4, 400, 24)


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


@pytest.fixture
def pictures(tmp_path):
    return LinePictures(tmp_path / "lines")


def saved(store, pictures, match, shade, text, confidence=1.0, **kwargs):
    """A stored light reading with its picture; `shade` tells the fake engine which it is."""
    message = store.add_message(ts=T0 + shade, channel="match", text=text, speaker_raw="Pip",
                                match_id=match, ocr_confidence=confidence, **kwargs)  # fmt: skip
    pictures.save(message, T0 + shade, np.full((32, 400, 3), shade, np.uint8), BOX)
    return message


def engine(readings):
    """The best engine: what it reads from the picture of each shade."""
    return lambda image: [OcrLine(readings[int(image[0, 0, 0])], 0.97, BOX)]


def evening(store, pictures):
    match = store.start_match(store.start_session(T0), T0, "heroselect", "COMPETITIVE")
    words = saved(store, pictures, match, 10, "I have")  # light lost "cookies"
    fine = saved(store, pictures, match, 20, "gg wp")
    edited = saved(store, pictures, match, 30, "tracer")
    store.edit_message(edited, "Tracer!", T0 + 99)  # fixed by hand
    return match, words, fine, edited


def test_only_better_readings_replace_and_hand_fixed_lines_stay(store, pictures):
    match, words, fine, edited = evening(store, pictures)
    reads = {10: "[Pip]: I have cookies", 20: "[Pip]: gg", 30: "[Pip]: tracer come here"}
    again = ReadAgain(store, pictures, engine(reads), idle=lambda: True)
    job = again.match(match)
    assert job.ids == [words, fine]  # the hand-fixed line isn't even read
    while again.run_once():
        pass
    assert job.finished and job.better == [words]
    assert [m.text for m in store.messages(match)] == ["I have cookies", "gg wp", "Tracer!"]
    # "gg" has fewer letters and the light reading's confidence was unknown (1.0): no change


def test_it_waits_while_a_match_runs(store, pictures):
    match, words, *_ = evening(store, pictures)
    running = [True]
    again = ReadAgain(store, pictures, engine({10: "[Pip]: I have cookies"}),
                      idle=lambda: not running[0])  # fmt: skip
    job = again.line(words)
    assert not again.run_once() and job.done == 0
    running[0] = False
    assert again.run_once() and job.better == [words]


def test_a_line_without_picture_or_fixed_by_hand_has_nothing_to_read(store, pictures):
    match, words, fine, edited = evening(store, pictures)
    no_picture = store.add_message(ts=T0 + 50, channel="match", text="x", match_id=match)
    again = ReadAgain(store, pictures, engine({}), idle=lambda: True)
    assert again.line(no_picture).finished and again.line(edited).finished


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_the_match_button_says_how_it_went(user: User, store, pictures, monkeypatch):
    config.save_setup_state("done")
    match, words, *_ = evening(store, pictures)
    again = ReadAgain(store, pictures, engine({10: "[Pip]: I have cookies", 20: "[Pip]: gg"}),
                      idle=lambda: True)  # fmt: skip
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "pictures", pictures)
    monkeypatch.setattr(runtime, "read_again", again)
    await user.open("/")
    user.find(marker="nav-sessions").click()
    user.find(marker=f"session-{store.latest_session()[0]}").click()
    user.find(marker=f"match-{match}").click()
    await user.should_see("I have")
    user.find(marker="read-again").click()
    await user.should_see("Reading 2 lines again")
    while again.run_once():
        pass
    await user.should_see("Read 2 lines again: 1 better.")
    await user.should_see("I have cookies")  # in its row at once
    await user.should_see("lines I never saw can't be found")


async def test_one_line_from_its_popup(user: User, store, pictures, monkeypatch):
    config.save_setup_state("done")
    match, words, *_ = evening(store, pictures)
    again = ReadAgain(store, pictures, engine({10: "[Pip]: I have cookies"}), idle=lambda: True)
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "pictures", pictures)
    monkeypatch.setattr(runtime, "read_again", again)
    await user.open("/")
    user.find(marker="nav-sessions").click()
    user.find(marker=f"session-{store.latest_session()[0]}").click()
    user.find(marker=f"match-{match}").click()
    user.find(marker=f"line-{words}").click()
    user.find(marker="read-line-again").click()
    assert again.run_once()
    await user.should_see("Read again: better now.")
    assert store.message(words).text == "I have cookies"

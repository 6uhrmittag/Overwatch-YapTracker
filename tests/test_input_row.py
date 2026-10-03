"""The chat's input line is never stored (#254): found by its frame, not by its text."""

import numpy as np
import pytest

from yaptracker.capture.source import Region
from yaptracker.input_row import input_band, without_input
from yaptracker.matches import MatchTracker
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import parse
from yaptracker.pause import Pause
from yaptracker.reader import ChatReader
from yaptracker.store.repo import Store

H, W = 395, 615  # the 1440p chat box
FRAME = (230, 230, 230)


def open_chat() -> np.ndarray:
    """Dark chat panel with the light-framed typing field at the bottom, as at 1440p."""
    image = np.full((H, W, 3), 20, np.uint8)
    image[338:341, 140:600] = image[383:386, 140:600] = FRAME  # top and bottom edge
    image[338:386, 140:143] = image[338:386, 597:600] = FRAME  # sides
    image[355:368, 160:200] = 255  # typed letters
    return image


def line(text, y):
    return OcrLine(text, 0.99, Region(64, y, 400, 24))


def test_the_open_field_is_found_and_closed_chat_has_none():
    assert input_band(open_chat()) == (338, 385)
    assert input_band(np.full((H, W, 3), 20, np.uint8)) is None


def test_two_edges_of_a_bright_scene_behind_closed_chat_are_not_a_field():
    scene = np.full((H, W, 3), 20, np.uint8)
    scene[338:386] = (255, 255, 180)  # a bright, coloured wall (BGR cyan): not dark inside
    scene[338:341] = scene[383:386] = FRAME
    assert input_band(scene) is None


def test_a_frame_high_in_the_box_is_not_the_field():
    high = np.full((H, W, 3), 20, np.uint8)
    high[150:153, 140:600] = high[195:198, 140:600] = FRAME
    assert input_band(high) is None


def test_the_typed_line_and_its_prompt_are_dropped_the_chat_above_kept():
    lines = [line("[Pickle]: hi", 290), line("[Mateh] hi: there", 350)]
    assert [kept.text for kept in without_input(lines, open_chat())] == ["[Pickle]: hi"]


@pytest.mark.parametrize("text", ["[Mateh] hi there", "Match] hi: there", "[Gruop] ok"])
def test_a_misread_prompt_is_the_input_line_too(text):
    (parsed,) = parse([line(text, 350)])
    assert parsed.kind == "input"


@pytest.mark.parametrize("text", ["[Teams] started playing Overwatch.", "[Mateo]: hi"])
def test_names_close_to_a_prompt_still_count(text):
    (parsed,) = parse([line(text, 100)])
    assert parsed.kind != "input"


def test_nothing_from_the_field_is_stored_and_no_player_is_made(tmp_path):
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        tracker = MatchTracker(store, Pause())
        tracker.capture_alive(1000.0)
        image = open_chat()
        typed = [line("[Pickle]: hi", 290), line("[Mateh] hi: there", 350)]
        reader = ChatReader(lambda _: typed, store, tracker)
        reader.read_frame(1000.0, image)
        assert [m.speaker_raw for m in store.messages(tracker.match_id)] == ["Pickle"]
        sent = np.full((H, W, 3), 20, np.uint8)  # sent: the field closed, the line is chat now
        reader = ChatReader(lambda _: [line("[Pickle]: hi", 266), line("[Marv]: hi: there", 290)],
                            store, tracker)  # fmt: skip
        reader.read_frame(1005.0, sent)
        assert [m.text for m in store.messages(tracker.match_id)][-1] == "hi: there"
        assert not any("Mateh" in (m.speaker_raw or "") for m in store.messages(tracker.match_id))
    finally:
        store.close()

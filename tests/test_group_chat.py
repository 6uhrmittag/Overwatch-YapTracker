"""Group chat (#80): its colour is learned from the open chat box's "[Group]" prompt and from
"...'s group wants to stay as a team"; then group lines are "group". Drawn frames, no names."""

import cv2
import numpy as np

from yaptracker import channels
from yaptracker.capture.source import Region
from yaptracker.dedup import Dedup
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import parse
from yaptracker.reader import ChatReader

H = 36
YELLOW, MAGENTA = (60, 235, 245), (235, 60, 230)  # BGR: team text and group text that evening


def frame(rows):
    """rows: (icon, text, colour); icon "team" (three people), "group" (two people) or None."""
    image = np.full((60 + len(rows) * 50, 900, 3), 12, np.uint8)
    lines = []
    for i, (icon, text, colour) in enumerate(rows):
        x, y = 100, 30 + i * 50
        cx, cy = int(x - 0.85 * H), y + H // 2
        heads = {"team": (-12, 0, 12), "group": (-6, 6)}.get(icon, ())
        for dx in heads:
            cv2.circle(image, (cx + dx, cy - 6), 3, colour, -1)
            cv2.ellipse(image, (cx + dx, cy + 6), (4, 6), 0, 0, 360, colour, -1)
        cv2.rectangle(image, (x, y + 8), (x + 12 * len(text), y + H - 8), colour, -1)
        lines.append(OcrLine(text, 0.99, Region(x, y, 12 * len(text), H)))
    return image, lines


def test_the_group_prompt_and_the_stay_together_line_teach_the_group_colour():
    image, ocr = frame([(None, "Pickle's group wants to stay as a team", MAGENTA),
                        (None, "[Group]", MAGENTA)])  # fmt: skip
    learned = channels.learn(parse(ocr), image)
    assert set(learned) == {"group"}  # not "system": that line is in the group colour
    assert channels.hue_distance(learned["group"], 302) < 10


def test_with_the_group_colour_known_group_lines_are_group():
    image, ocr = frame([("group", "[Pickle]: nyello", MAGENTA), ("team", "[Moon]: on it", YELLOW),
                        (None, "[Pickle]: luv u", MAGENTA)])  # fmt: skip
    learned = channels.learn(parse(ocr), image)
    known = {"group": channels.text_hue(image, ocr[0].box)}
    assert [line.channel for line in channels.assign(parse(ocr), image, known)] == [
        "group", "team", "group",
    ]  # fmt: skip
    assert "team" in learned


def test_without_it_they_stay_unknown_rather_than_a_guess():
    image, ocr = frame([("group", "[Pickle]: nyello", MAGENTA)])
    assert [line.channel for line in channels.assign(parse(ocr), image, {})] == ["unknown"]


def test_the_reader_keeps_a_learned_group_colour_for_next_time():
    image, ocr = frame([("group", "[Pickle]: nyello", MAGENTA), (None, "[Group]", MAGENTA)])
    saved, colours = [], {}

    class Store:  # just enough store for one frame
        def __getattr__(self, name):
            return lambda *a, **k: 1

    class Matches:
        match_id = 1

        def chat_changed(self, ts):
            pass

    reader = ChatReader(lambda img: ocr, Store(), Matches(), colours=lambda: colours,
                        save_colours=saved.append)  # fmt: skip
    reader._dedup = Dedup()
    stored = reader.read_frame(1.0, image)
    assert saved and "group" in saved[0]
    assert [y.best.channel for y in stored] == ["group"]

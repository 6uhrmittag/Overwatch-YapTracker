import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from yaptracker import channels
from yaptracker.capture.source import Region
from yaptracker.parser import ChatLine

ORANGE, GREEN, YELLOW, RED = (255, 174, 77), (130, 220, 60), (255, 214, 90), (230, 40, 40)


def frame(rows: list[tuple[str, tuple[int, int, int]]]) -> tuple[np.ndarray, list[Region]]:
    """Coloured text rows on a dark background, like the closed chat over a dark scene."""
    img = Image.new("RGB", (600, 40 * len(rows) + 20), (20, 24, 30))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=24)
    boxes = []
    for i, (text, colour) in enumerate(rows):
        draw.text((10, 10 + 40 * i), text, fill=colour, font=font)
        boxes.append(Region(10, 10 + 40 * i, 580, 30))
    return np.ascontiguousarray(np.asarray(img)[:, :, ::-1]), boxes


def line(kind, box, channel="unknown"):
    return ChatLine(kind=kind, channel=channel, text="x", confidence=1.0, box=box)


def test_typed_lines_get_the_channel_whose_colour_they_have():
    rows = [
        ("Ana (Ana): Thanks!", GREEN),
        ("[Bo]: in team chat", GREEN),
        ("[Cy]: in match chat", ORANGE),
        ("[Di] started playing.", YELLOW),
    ]
    image, boxes = frame(rows)
    kinds = [
        ("comms", "team"),
        ("message", "unknown"),
        ("message", "unknown"),
        ("system", "system"),
    ]
    lines = [line(kind, box, channel) for (kind, channel), box in zip(kinds, boxes, strict=True)]
    assert [c.channel for c in channels.assign(lines, image)] == ["team", "team", "match", "system"]


def test_learns_team_and_system_colours_from_what_the_text_proves():
    image, boxes = frame([("Ana (Ana): Thanks!", GREEN), ("[Di] started playing.", YELLOW)])
    learned = channels.learn([line("comms", boxes[0]), line("system", boxes[1])], image)
    assert learned["team"] == pytest.approx(90, abs=6)
    assert learned["system"] == pytest.approx(46, abs=6)


def test_unsure_colours_stay_unknown():
    image, boxes = frame(
        [("[Bo]: red streak over the chat", RED), ("[Cy]: team, never seen", GREEN)]
    )
    lines = [line("message", boxes[0]), line("message", boxes[1])]
    assert [c.channel for c in channels.assign(lines, image)] == ["unknown", "unknown"]


def test_colours_saved_at_calibration_are_used_when_the_frame_proves_nothing():
    image, boxes = frame([("[Cy]: team chat", GREEN)])
    known = {"team": channels.text_hue(image, boxes[0])}
    assert channels.assign([line("message", boxes[0])], image, known)[0].channel == "team"

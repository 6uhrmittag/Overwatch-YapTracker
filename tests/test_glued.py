"""Background text glued to chat lines on bright frames is cut by its colour (#172)."""

import json
from pathlib import Path

import numpy as np

from yaptracker import channels
from yaptracker.capture.source import Region
from yaptracker.dedup import Dedup
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import parse

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "dedup" / "172-glued.json").read_text(
    encoding="utf-8"))  # fmt: skip


def test_a_real_bright_frame_keeps_only_the_chat():
    hues, lines = {}, []
    for line in FIXTURE["lines"]:
        parts = tuple((p["text"], Region(*p["box"])) for p in line["parts"])
        for (_, box), p in zip(parts, line["parts"], strict=True):
            hues[box] = p["hue"]
        x0 = min(b.x for _, b in parts)
        box = Region(x0, parts[0][1].y, max(b.x + b.width for _, b in parts) - x0,
                     parts[0][1].height)  # fmt: skip
        lines.append(OcrLine(" ".join(t for t, _ in parts), line["confidence"], box, parts))
    cut = channels.cut_glued(lines, None, FIXTURE["known"], hue=lambda image, box: hues[box])
    stored, _ = Dedup().update(0.0, parse(cut))
    assert [(y.best.speaker, y.best.text) for y in stored] == [
        ("Pickle", "Can i? DESTINATION"),  # its own text came out sky blue: left alone
        ("MoonPebble", "gg yall"),  # was "gg yall TRAINNO"
        ("BoltBucket", "gg"),  # was "gg 5 512"
        ("tortillaTank", "i luv u puuupsss"),  # was "... 1732"
        ("MoonPebble", "glhf next :3"),
        ("kittycat", "pickle ur a goid boy"),  # was "... 利 2325"
        ("tortillaTank", "fun game :3"),  # was "... 236"
    ]  # and "NE", "B7": not chat, not stored


def test_words_in_the_chat_colour_stay_glued_ones_go():
    image = np.full((40, 400, 3), 20, np.uint8)
    image[10:30, 10:150] = (60, 220, 230)  # yellow chat text (BGR)
    image[10:30, 160:200] = (70, 210, 240)  # more of it: "and 2v2" said in chat
    image[10:30, 300:360] = (230, 160, 60)  # a blue sign behind the box
    parts = (("[Pickle]: gg", Region(10, 10, 140, 20)), ("2v2", Region(160, 10, 40, 20)),
             ("512", Region(300, 10, 60, 20)))  # fmt: skip
    line = OcrLine("[Pickle]: gg 2v2 512", 0.9, Region(10, 10, 350, 20), parts)
    (cut,) = channels.cut_glued([line], image)
    assert cut.text == "[Pickle]: gg 2v2" and cut.box == Region(10, 10, 190, 20)

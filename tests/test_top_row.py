"""The top row cut off by the opened chat's edge is told by its picture (#632)."""

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from yaptracker import top_row
from yaptracker.capture.source import Region
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import parse

ROW, HEIGHT = 40, 24
TEXTS = ["[Pickle]: Heyyy", "[Pickle]: glhf <3", "NoodleBonk (Ana): Hello!", "[Bo]: gg wp"]


def chat(cut_px: int = 0) -> tuple[np.ndarray, list[Region]]:
    """Four chat rows on a dark panel; the top one loses its upper `cut_px` pixel rows, as the
    edge of the opened chat box takes them."""
    image = Image.new("RGB", (420, 20 + ROW * len(TEXTS)), (12, 12, 12))
    draw, font = ImageDraw.Draw(image), ImageFont.load_default(size=HEIGHT)
    boxes = []
    for n, text in enumerate(TEXTS):
        y = 10 + ROW * n
        draw.text((60, y), text, font=font, fill=(240, 170, 90))
        left, top, right, bottom = draw.textbbox((60, y), text, font=font)
        boxes.append(Region(left, top, right - left, bottom - top))
    picture = np.asarray(image).copy()
    picture[: boxes[0].y + cut_px] = (90, 60, 40)  # the game behind, above the box's edge
    return picture[:, :, ::-1], boxes


def test_a_whole_top_row_is_not_cut():
    image, boxes = chat()
    assert not top_row.clipped(image, boxes[0], boxes[1:])


def test_a_top_row_with_its_upper_half_gone_is_cut():
    image, boxes = chat(cut_px=boxes_height() // 2)
    assert top_row.clipped(image, boxes[0], boxes[1:])


def boxes_height() -> int:
    return chat()[1][0].height


def test_a_row_boxed_much_lower_than_the_others_is_cut():
    """A line fading out: detection boxes what is left of it."""
    image, boxes = chat()
    faded = Region(boxes[0].x, boxes[0].y + 8, boxes[0].width, boxes[0].height - 12)
    assert top_row.clipped(image, faded, boxes[1:])


def test_a_lone_line_or_one_with_a_single_row_below_is_never_judged():
    image, boxes = chat(cut_px=boxes_height() // 2)
    assert not top_row.clipped(image, boxes[0], [])
    assert not top_row.clipped(image, boxes[0], boxes[1:2])


def _lines(confidence: float) -> list[OcrLine]:
    _image, boxes = chat()
    texts = ["[Plckte]: Heyyy", *TEXTS[1:]]  # how the chat-trained reader read the half row
    scores = [confidence, 0.98, 0.99, 0.99]
    return [OcrLine(t, c, b) for t, c, b in zip(texts, scores, boxes, strict=True)]


def test_a_weak_line_shaped_top_row_is_cut_only_when_the_picture_says_so():
    assert parse(_lines(0.88))[0].kind == "message"  # as before: weak, read again
    assert parse(_lines(0.88), clipped=lambda box, below: True)[0].kind == "cut"
    assert [line.kind for line in parse(_lines(0.88), clipped=lambda box, below: True)[1:]] == [
        "message", "comms", "message"]  # fmt: skip


def test_a_well_read_top_row_stays_whatever_the_picture_measure_says():
    """The measure is fooled by a busy background now and then: it never decides alone."""
    assert parse(_lines(0.97), clipped=lambda box, below: True)[0].kind == "message"


def test_a_whole_row_in_a_darker_colour_than_the_rows_below_is_not_cut():
    """Channel colours are user settings: a dim team line above bright match chat is whole."""
    image, boxes = chat()
    top = boxes[0]
    dim = image.copy()
    region = dim[top.y - 2 : top.y + top.height + 2, top.x : top.x + top.width]
    region[region.max(axis=2) > 60] = (60, 90, 70)  # the letters, darker than the others
    assert not top_row.clipped(dim, top, boxes[1:])


def test_a_long_row_with_few_tall_letters_is_not_cut():
    image = Image.new("RGB", (900, 140), (12, 12, 12))
    draw, font = ImageDraw.Draw(image), ImageFont.load_default(size=HEIGHT)
    boxes = []
    for n, text in enumerate(["[Bo]: owo uwu ooo nooo owo uwu ooo nooo owo uwu", *TEXTS[1:3]]):
        y = 10 + ROW * n
        draw.text((60, y), text, font=font, fill=(240, 170, 90))
        left, top, right, bottom = draw.textbbox((60, y), text, font=font)
        boxes.append(Region(left, top, right - left, bottom - top))
    picture = np.asarray(image)[:, :, ::-1].copy()
    assert not top_row.clipped(picture, boxes[0], boxes[1:])


def test_boxes_outside_the_picture_dont_raise():
    image, boxes = chat()
    outside = Region(5000, 5000, 100, 20)
    assert not top_row.clipped(image, outside, boxes[1:])
    assert not top_row.clipped(image, boxes[0], [outside, outside, Region(0, 0, 0, 0)])

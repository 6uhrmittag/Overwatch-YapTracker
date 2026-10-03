"""Umlauts found in the picture (#247): the default model reads "täääätüüüü" as "taaaatuuuu",
which doesn't look German, so the line picture decides whether the Latin model reads it too."""

from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from yaptracker.ocr import engine as ocr
from yaptracker.ocr.engine import has_umlaut_dots, keep_repeats

FONT = Path(__file__).parents[1] / "src" / "yaptracker" / "ui" / "static" / "fonts" / \
    "nunito-sans-latin.woff2"  # fmt: skip
GROUNDS = [(40, 44, 52), (90, 110, 150), (150, 90, 60)]  # night, sky, a warm wall


def line(text: str, ground=(40, 44, 52), size: int = 30) -> np.ndarray:
    """One chat line as the recogniser gets it: coloured text with a dark edge."""
    font = ImageFont.truetype(str(FONT), size)
    img = Image.new("RGB", (int(font.getlength(text)) + 20, 48), ground)
    ImageDraw.Draw(img).text((10, 4), text, fill=(255, 174, 77), font=font, stroke_width=1,
                             stroke_fill=(10, 10, 10))  # fmt: skip
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


UMLAUT_LINES = ["[Marv]: täääätüüüütatäääää", "[Pickle]: nö", "[Pickle]: jüt",
                "[Pickle]: Müller", "[Pickle]: schön", "[Pickle]: Grüße"]  # fmt: skip


@pytest.mark.parametrize("ground", GROUNDS)
@pytest.mark.parametrize("text", UMLAUT_LINES)
def test_umlaut_dots_are_seen(text, ground):
    assert has_umlaut_dots(line(text, ground))


@pytest.mark.parametrize("text", ["[Marv]: taaaatuuuutataaaaaa", "it is literally the first fight",
                                  "jij iii jinx", 'he said "hi"', "[x]: ok: fine"])  # fmt: skip
def test_i_dots_quotes_and_colons_are_not_umlauts(text):
    assert not has_umlaut_dots(line(text))


def read_box(text: str, size: int = 22) -> str:
    font = ImageFont.truetype(str(FONT), size)
    img = Image.new("RGB", (615, 80), (40, 44, 52))
    ImageDraw.Draw(img).text((14, 20), text, fill=(255, 174, 77), font=font, stroke_width=2,
                             stroke_fill=(10, 10, 10))  # fmt: skip
    (read,) = ocr.get("rapidocr").read(np.ascontiguousarray(np.asarray(img)[:, :, ::-1]))
    return read.text


@pytest.mark.parametrize("text", ["[Pickle]: jüt Müller schön", "[Marv]: tätütatä",
                                  "[Pickle]: nö, Grüße"])  # fmt: skip
def test_short_lines_without_a_german_word_keep_their_umlauts(text):
    assert read_box(text) == text  # before #247: "jut Muller schon", "tatutata", "no, GruBe"


def test_marvs_line_gets_its_umlauts_back():
    """The Latin model squeezes long runs of one letter ("ääää"), the default model keeps the
    count: run by run, the counts from one and the umlauts from the other."""
    read = read_box("[Marv]: täääätüüüütatäääää", size=28)
    assert "üüüü" in read and read.startswith("[Marv]: t")


def test_keep_repeats():
    assert keep_repeats("taaaatuuuuta", "taatüüta") == "taaaatüüüüta"
    assert keep_repeats("Schone Grube", "Schöne Grüße") == "Schöne Grüße"  # not shorter: Latin
    assert keep_repeats("taaaatuuuu", "ttüü") == "ttüü"  # runs don't line up: Latin as it is


def test_the_check_is_cheap():
    import time

    crop = line("[tortillaTank]: not the wahoo guy again lmao")
    started = time.perf_counter()
    for _ in range(20):
        has_umlaut_dots(crop)
    assert (time.perf_counter() - started) / 20 < 0.005  # well under the ~250 ms of a read

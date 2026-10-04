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


def line(text: str, ground=(40, 44, 52), size: int = 44) -> np.ndarray:
    """One chat line as the recogniser gets it: coloured text with a dark edge. Nunito's dots
    are smaller than the game's: at 44 px they're the 3 px squares of real chat crops."""
    font = ImageFont.truetype(str(FONT), size)
    img = Image.new("RGB", (int(font.getlength(text)) + 20, 70), ground)
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


def read_box(text: str, size: int = 34) -> str:
    font = ImageFont.truetype(str(FONT), size)
    img = Image.new("RGB", (900, 80), (40, 44, 52))
    ImageDraw.Draw(img).text((14, 20), text, fill=(255, 174, 77), font=font, stroke_width=2,
                             stroke_fill=(10, 10, 10))  # fmt: skip
    (read,) = ocr.get("rapidocr").read(np.ascontiguousarray(np.asarray(img)[:, :, ::-1]))
    return read.text


@pytest.mark.parametrize("text", ["[Pickle]: jüt Müller schön", "[Marv]: tätütatä",
                                  "[Pickle]: nö, Grüße"])  # fmt: skip
def test_short_lines_without_a_german_word_keep_their_umlauts(text):
    assert read_box(text) == text  # before #247: "jut Muller schon", "tatutata", "no, GruBe"


def test_marvs_line_gets_its_umlauts_back():
    """The Latin model squeezes long runs of one letter ("ääää"), and can drop a whole run; the
    default model keeps every letter. Run by run, or (#266) by the dots' places in the picture:
    each a, o or u under a dot pair becomes ä, ö or ü."""
    for size in (34, 38):
        assert read_box("[Marv]: täääätüüüütatäääää", size=size) == "[Marv]: täääätüüüütatäääää"


def test_the_dots_only_step_in_for_long_runs():
    """A German line without a long run keeps the Latin reading (its ß, its letters): the dot
    fallback once turned "Weißt du" into "Weilt du" (#266)."""
    assert (
        read_box("[Sören]: Weißt du, wo der Heiler ist?") == "[Sören]: Weißt du, wo der Heiler ist?"
    )


def test_slivers_on_letter_tops_are_not_dots():
    """What fired on 24 of 80 English 4K frames: 1-2 px slivers of anti-aliasing on the tops of
    C, d or ], side by side above a letter. Real umlaut dots are filled 3-4 px squares."""
    crop = np.full((50, 60, 3), (52, 44, 40), np.uint8)
    yellow = (77, 174, 255)
    crop[20:45, 20:40] = yellow  # a letter
    crop[12:13, 22:24] = crop[12:13, 30:32] = yellow  # 2x1 slivers
    assert not has_umlaut_dots(crop)
    crop[12:13, 22:24] = crop[12:13, 30:32] = (52, 44, 40)
    crop[10:13, 22:25] = crop[10:13, 30:33] = yellow  # two 3x3 dots
    assert has_umlaut_dots(crop)
    crop[10:13, 30:33] = (52, 44, 40)
    crop[8:13, 30:35] = yellow  # one dot much bigger than the other
    assert not has_umlaut_dots(crop)


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

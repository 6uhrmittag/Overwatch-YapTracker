"""Emoji and icons become "◇" (#128): real OCR on rendered chat lines, and plain text untouched."""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from yaptracker import glyphs
from yaptracker.ocr import engine as ocr

FONT = Path(__file__).parents[1] / "src" / "yaptracker" / "ui" / "static" / "fonts"
LIME, DARK = (190, 225, 90), (40, 44, 52)
ICON, HEART = "<icon>", "<heart>"


def chat(*pieces) -> np.ndarray:
    """A chat box with one line: text pieces and ICON / HEART blobs, left to right."""
    font = ImageFont.truetype(str(FONT / "nunito-sans-latin.woff2"), 22)
    img = Image.new("RGB", (615, 80), DARK)
    draw = ImageDraw.Draw(img)
    x, y = 14, 28
    for piece in pieces:
        if piece not in (ICON, HEART):
            draw.text((x, y), piece, fill=LIME, font=font, stroke_width=2, stroke_fill=(10, 10, 10))
            x += int(draw.textlength(piece, font=font)) + 6
        elif piece == ICON:  # Overwatch's own chat icons: white-grey, e.g. the thumbs-up
            draw.rounded_rectangle((x + 4, y + 2, x + 24, y + 26), radius=6, fill=(225, 225, 230))
            x += 40
        else:  # a red heart
            draw.ellipse((x + 4, y + 4, x + 16, y + 16), fill=(220, 30, 40))
            draw.ellipse((x + 13, y + 4, x + 25, y + 16), fill=(220, 30, 40))
            draw.polygon([(x + 5, y + 12), (x + 24, y + 12), (x + 14, y + 26)], fill=(220, 30, 40))
            x += 40
    return np.ascontiguousarray(np.asarray(img)[:, :, ::-1])


def read(image) -> list[str]:
    return [line.text.strip() for line in glyphs.mark(image, ocr.get("rapidocr").read(image))]


def test_an_icon_after_the_text_becomes_a_diamond():
    assert read(chat("[NoodleBonk]: Thanks!", ICON)) == ["[NoodleBonk]: Thanks! ◇"]


def test_a_heart_too():
    assert read(chat("[zappy]: love you all", HEART)) == ["[zappy]: love you all ◇"]


def test_an_icon_between_words_lands_between_them():
    assert read(chat("[zappy]: good", ICON, "game")) == ["[zappy]: good ◇ game"]


def test_plain_text_gets_no_diamond():
    assert read(chat("[mossyfox]: gl hf, have fun")) == ["[mossyfox]: gl hf, have fun"]


CROPS = Path(__file__).parent / "fixtures" / "glyphs"


def after_the_text(name: str) -> bool:
    """The space right after a line's last word, cut from Void's 2026-10-16 frames (no text)."""
    (path,) = CROPS.glob(f"{name}-h*.png")
    crop = np.ascontiguousarray(np.asarray(Image.open(path).convert("RGB"))[:, :, ::-1])
    height = int(path.stem.rsplit("-h", 1)[1])
    return glyphs._blob(crop, 0, crop.shape[1], 0, crop.shape[0], height, after=True)


def test_scenery_behind_a_line_end_is_no_icon_but_a_comms_icon_is():
    """#475: 26 % of Void's lines got a ◇ from coloured scenery filling the row (pink chat)."""
    assert not after_the_text("red-hand-after-system-line")
    assert not after_the_text("pink-stroke-after-comms-line")
    assert not after_the_text("green-wall-after-comms-line")
    assert after_the_text("fall-back-arrow-icon")  # "Fall back!" really ends with an icon

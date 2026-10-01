from pathlib import Path

import numpy as np
import pytest

from yaptracker import config, demo
from yaptracker.capture.source import Region, default_chat_region
from yaptracker.ocr import engine as ocr
from yaptracker.ocr.engine import _Word, group_lines


def demo_chat_crop() -> np.ndarray:
    image = demo.screenshot()
    r = default_chat_region(image.width, image.height)
    rgb = np.asarray(image.crop((r.x, r.y, r.x + r.width, r.y + r.height)))
    return np.ascontiguousarray(rgb[:, :, ::-1])


def test_words_on_one_row_become_one_line_top_to_bottom():
    words = [
        _Word("second", 0.8, 10, 40, 60, 20),
        _Word("[Name]:", 0.9, 10, 10, 70, 20),
        _Word("hi", 0.7, 90, 12, 20, 18),
    ]
    lines = group_lines(words)
    assert [line.text for line in lines] == ["[Name]: hi", "second"]
    assert lines[0].confidence == pytest.approx(0.8)
    assert lines[0].box == Region(10, 10, 100, 20)


def test_rapidocr_reads_the_demo_chat():
    lines = ocr.get("rapidocr").read(demo_chat_crop())
    assert len(lines) == 6
    assert "wahoo guy again" in lines[1].text
    assert all(a.box.y < b.box.y for a, b in zip(lines, lines[1:], strict=False))


def test_rapidocr_reads_german_umlauts_and_still_reads_english():
    """#118: the default model turned this into "Schone GruBe"; the Latin one has the letters."""
    from PIL import Image, ImageDraw, ImageFont

    fonts = Path(__file__).parents[1] / "src" / "yaptracker" / "ui" / "static" / "fonts"
    font = ImageFont.truetype(str(fonts / "nunito-sans-latin.woff2"), 22)  # has the umlauts
    img = Image.new("RGB", (615, 120), (40, 44, 52))
    draw = ImageDraw.Draw(img)
    for y, colour, text in [
        (20, (255, 174, 77), "[Björn]: Schöne Grüße an alle, gg!"),
        (60, (124, 227, 139), "[NoodleBonk]: not the wahoo guy again"),
    ]:
        draw.text((14, y), text, fill=colour, font=font, stroke_width=2, stroke_fill=(10, 10, 10))
    lines = ocr.get("rapidocr").read(np.ascontiguousarray(np.asarray(img)[:, :, ::-1]))
    assert [line.text for line in lines] == [
        "[Björn]: Schöne Grüße an alle, gg!",
        "[NoodleBonk]: not the wahoo guy again",
    ]


def test_engine_setting_falls_back_when_the_engine_cant_run_here(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    assert config.ocr_engine(path) == "rapidocr"
    config.save_ocr_engine("windows", path)
    monkeypatch.setattr(ocr, "available", lambda: ["rapidocr"])
    assert config.ocr_engine(path) == "rapidocr"
    monkeypatch.setattr(ocr, "available", lambda: ["rapidocr", "windows"])
    assert config.ocr_engine(path) == "windows"


def test_german_looking_lines_are_read_again_english_ones_not():
    """#115: the Latin model only reads again when the default reading looks German."""
    from yaptracker.ocr.engine import looks_german

    # how the default model really reads German chat (#118): ß as B/f/b, umlauts dropped
    for text in [
        "[Kokirk]: Schone GruBe an alle, gg!",
        "[Björn]: GroBe, FuBe, Arger",
        "[VoidCrowned]: SuB :3",
        "[Fubball]: Gruf Gott",
        "Ich heile dich!",
        "[Zoe]: Ubermorgen wieder?",
        "[x]: Tschuss, bis spater",
        "danke fur das Spiel",
    ]:
        assert looks_german(text), text
    for text in [
        "[NoodleBonk]: WAHOOOO",
        "[tortillaTank]: not the wahoo guy again lmao",
        "SirPeelsALot (Reinhardt): Group up!",
        "[x]: maybe later, gg wp",
        "[x]: im hanging",
        "You endorsed NoodleBonk!",
        "[x]: sooo good",
        "Enemy Tracer!",
    ]:
        assert not looks_german(text), text  # fmt: skip


def test_upscale_keeps_the_text_height_of_1440p_above_it():
    """#169: 2x up to 1440p as measured; at 4K only 1.33x, the same text height in pixels."""
    assert ocr.upscale_for(None) == ocr.upscale_for(1080) == ocr.upscale_for(1440) == 2.0
    assert ocr.upscale_for(2160) == pytest.approx(4 / 3)
    assert ocr.upscale_for(1600) == pytest.approx(1.8)


def test_a_4k_crop_reads_like_the_1440p_one():
    import cv2
    from rapidfuzz import fuzz

    crop = demo_chat_crop()
    at_4k = cv2.resize(crop, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    engine = ocr.get("rapidocr")
    expected = [line.text for line in engine.read(crop)]
    lines = engine.read(at_4k, scale=ocr.upscale_for(2160))
    assert len(lines) == len(expected)  # a synthetic upscale isn't a real 4K frame: near enough
    assert all(fuzz.ratio(a.text, b) >= 90 for a, b in zip(lines, expected, strict=True))
    assert lines[0].box.y == pytest.approx(engine.read(crop)[0].box.y * 1.5, abs=4)  # 4K pixels


def test_the_live_scale_follows_the_captured_window(monkeypatch):
    from yaptracker import runtime

    monkeypatch.setattr(runtime, "window_size", (3840, 2160))
    assert runtime.ocr_scale() == pytest.approx(4 / 3)
    monkeypatch.setattr(runtime, "window_size", None)
    assert runtime.ocr_scale() == 2.0

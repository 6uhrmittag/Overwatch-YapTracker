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


def test_engine_setting_falls_back_when_the_engine_cant_run_here(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    assert config.ocr_engine(path) == "rapidocr"
    config.save_ocr_engine("windows", path)
    monkeypatch.setattr(ocr, "available", lambda: ["rapidocr"])
    assert config.ocr_engine(path) == "rapidocr"
    monkeypatch.setattr(ocr, "available", lambda: ["rapidocr", "windows"])
    assert config.ocr_engine(path) == "windows"

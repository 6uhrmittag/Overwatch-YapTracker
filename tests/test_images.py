"""Pictures under any path (#459): cv2.imwrite/imread fail on Windows for C:\\Users\\Jürgen."""

import re
from pathlib import Path

import numpy as np

from yaptracker import images
from yaptracker.capture.source import Region
from yaptracker.lines import LinePictures

SRC = Path(__file__).parents[1] / "src" / "yaptracker"


def test_a_line_picture_is_saved_and_read_back_under_a_folder_with_umlauts(tmp_path):
    folder = tmp_path / "Jürgen Größe" / "lines"
    chat = np.zeros((395, 615, 3), np.uint8)
    chat[300:320, 70:200] = (40, 200, 255)
    saved = LinePictures(folder).save(7, 1000.0, chat, Region(64, 300, 300, 24))
    back = images.read(saved)
    assert saved.exists() and back is not None and back.shape[1] == 615
    assert (back[10, 80] == (40, 200, 255)).all()  # lossless
    assert images.read(folder / "missing.webp") is None


def test_no_cv2_file_reading_or_writing_left_in_the_app():
    found = [f"{p.relative_to(SRC)}:{n}" for p in SRC.rglob("*.py")
             for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
             if re.search(r"cv2\.(imwrite|imread)\(", line)]  # fmt: skip
    assert found == [], "use yaptracker.images (#459)"

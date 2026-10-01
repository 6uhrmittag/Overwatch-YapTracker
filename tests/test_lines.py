"""Line pictures (#120): every stored chat line keeps its picture, small, in colour, capped."""

import time

import cv2
import numpy as np

from yaptracker import demo
from yaptracker.capture.source import Region, default_chat_region
from yaptracker.lines import LinePictures

OCT = time.mktime((2026, 10, 1, 21, 0, 0, 0, 0, -1))


def demo_chat() -> np.ndarray:
    image = demo.screenshot()
    r = default_chat_region(image.width, image.height)
    return np.ascontiguousarray(
        np.asarray(image.crop((r.x, r.y, r.x + r.width, r.y + r.height)))[:, :, ::-1]
    )


def test_a_line_is_kept_in_colour_with_a_little_margin(tmp_path):
    chat = demo_chat()
    pictures = LinePictures(tmp_path / "lines")
    path = pictures.save(42, OCT, chat, Region(15, 290, 300, 24))
    assert path == tmp_path / "lines" / "2026-10" / "42.webp"
    saved = cv2.imread(str(path))
    assert saved.shape == (28, 304, 3)  # 2 px around the box
    assert np.array_equal(saved, chat[288:316, 13:317])  # lossless, colour
    assert path.stat().st_size < 10_000  # typical line < 10 kB


def test_a_better_reading_saves_over_it_and_switched_off_saves_nothing(tmp_path):
    chat = demo_chat()
    pictures = LinePictures(tmp_path / "lines")
    pictures.save(7, OCT, chat, Region(15, 290, 300, 24))
    pictures.save(7, OCT, chat, Region(15, 320, 300, 24))
    assert len(list((tmp_path / "lines").rglob("*.webp"))) == 1
    off = LinePictures(tmp_path / "off", enabled=lambda: False)
    assert off.save(8, OCT, chat, Region(15, 290, 300, 24)) is None


def test_the_oldest_months_go_first_once_over_the_cap(tmp_path):
    folder = tmp_path / "lines"
    for month, size in [("2026-08", 600), ("2026-09", 600), ("2026-10", 600)]:
        (folder / month).mkdir(parents=True)
        (folder / month / "1.webp").write_bytes(b"x" * size)
    LinePictures(folder, cap_bytes=1300).clean_up()
    assert sorted(p.name for p in folder.iterdir()) == ["2026-09", "2026-10"]

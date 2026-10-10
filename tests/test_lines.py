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


def test_a_line_is_kept_in_colour_as_its_whole_row(tmp_path):
    chat = demo_chat()
    pictures = LinePictures(tmp_path / "lines")
    path = pictures.save(42, OCT, chat, Region(150, 290, 100, 24))  # OCR's box cut the row
    assert path == tmp_path / "lines" / "2026-10" / "42.webp"
    saved = cv2.imread(str(path))
    # the whole row (#259): channel icon, whole name, trailing icons; 2 px above and below
    assert saved.shape == (28, chat.shape[1], 3)
    assert np.array_equal(saved, chat[288:316, :])  # lossless, colour
    assert path.stat().st_size < 20_000  # typical line well under 20 kB


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
    LinePictures(folder, cap_bytes=1300).start(background=False)
    assert sorted(p.name for p in folder.iterdir()) == ["2026-09", "2026-10"]

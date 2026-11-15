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


def month_of(folder, month, sizes):
    (folder / month).mkdir(parents=True, exist_ok=True)
    for message_id, size in sizes.items():
        (folder / month / f"{message_id}.webp").write_bytes(b"x" * size)


def test_a_cap_below_this_month_takes_only_its_oldest_pictures(tmp_path):
    """#462: the month being written never goes as a whole; the newest line's picture stays."""
    folder = tmp_path / "lines"
    month_of(folder, "2026-09", {1: 500})
    month_of(folder, "2026-10", {9: 400, 10: 400, 11: 400, 12: 400})
    pictures = LinePictures(folder, cap_bytes=900)
    pictures.start(background=False)
    assert sorted(p.name for p in folder.iterdir()) == ["2026-10"]
    assert sorted(p.name for p in (folder / "2026-10").iterdir()) == ["11.webp", "12.webp"]
    assert pictures.size_bytes() == 800
    tiny = LinePictures(folder, cap_bytes=10)  # even a cap below one picture keeps the newest
    tiny.start(background=False)
    assert [p.name for p in (folder / "2026-10").iterdir()] == ["12.webp"]


def test_save_and_clean_up_never_interleave(tmp_path):
    """#462: a clean-up from Settings held the folder while a line was saved into it."""
    import threading

    pictures = LinePictures(tmp_path / "lines")
    pictures.start(background=False)
    done = threading.Event()
    with pictures._lock:  # a clean-up running
        threading.Thread(target=lambda: (pictures.save(5, OCT, demo_chat(),
                                                       Region(15, 290, 300, 24)),
                                         done.set()), daemon=True).start()  # fmt: skip
        assert not done.wait(0.3)  # the save waits for it
    assert done.wait(5)
    assert pictures.path(5, OCT).exists()


def test_a_picture_that_cant_be_deleted_stays_counted(tmp_path, monkeypatch):
    """#462: open in the UI (Windows), it stays; the tally must not forget it."""
    from pathlib import Path

    from yaptracker import lines

    folder = tmp_path / "lines"
    month_of(folder, "2026-08", {1: 500})
    month_of(folder, "2026-10", {7: 300, 8: 300, 9: 300})
    stuck = {folder / "2026-08" / "1.webp", folder / "2026-10" / "7.webp"}
    unlink = Path.unlink

    def locked(path, missing_ok=False):
        if path in stuck:
            raise PermissionError("in use")
        unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", locked)
    monkeypatch.setattr(lines.shutil, "rmtree", lambda path, ignore_errors=False: None)
    pictures = LinePictures(folder, cap_bytes=400)
    pictures.start(background=False)
    left = {p for p in folder.rglob("*.webp")}
    assert left == stuck | {folder / "2026-10" / "9.webp"}
    assert pictures.size_bytes() == sum(p.stat().st_size for p in left) == 1100

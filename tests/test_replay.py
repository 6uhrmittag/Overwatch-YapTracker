import numpy as np
import pytest
from PIL import Image

from yaptracker.capture.replay import ReplayFrameSource, main
from yaptracker.capture.source import Region


def _write(folder, name, rgb=(255, 0, 0), size=(8, 6)):
    Image.new("RGB", size, rgb).save(folder / name)


def test_frames_in_name_order_spaced_by_fps(tmp_path):
    for name in ["b.png", "a.png", "c.png", "notes.txt"]:
        if name.endswith(".png"):
            _write(tmp_path, name)
        else:
            (tmp_path / name).write_text("ignored")
    source = ReplayFrameSource(tmp_path, fps=4)
    assert [p.name for p in source.paths] == ["a.png", "b.png", "c.png"]
    assert [f.ts for f in source.frames()] == [0.0, 0.25, 0.5]


def test_millisecond_names_give_real_timing(tmp_path):
    for name in ["001000.png", "001250.png", "002750.png"]:
        _write(tmp_path, name)
    assert [f.ts for f in ReplayFrameSource(tmp_path).frames()] == [0.0, 0.25, 1.75]


def test_images_are_bgr_uint8(tmp_path):
    _write(tmp_path, "a.png", rgb=(255, 0, 0))
    frame = next(ReplayFrameSource(tmp_path).frames())
    assert frame.image.dtype == np.uint8
    assert frame.image.shape == (6, 8, 3)
    assert tuple(frame.image[0, 0]) == (0, 0, 255)


def test_region_crops_every_frame(tmp_path):
    _write(tmp_path, "a.png", size=(100, 50))
    frame = next(ReplayFrameSource(tmp_path, region=Region(10, 5, 30, 20)).frames())
    assert frame.image.shape == (20, 30, 3)


def test_realtime_waits_for_each_timestamp(tmp_path):
    for name in ["000000.png", "000500.png", "001500.png"]:
        _write(tmp_path, name)
    now = [100.0]
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds

    source = ReplayFrameSource(tmp_path, realtime=True, clock=lambda: now[0], sleep=sleep)
    list(source.frames())
    assert waits == [0.5, 1.0]


def test_empty_folder_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        ReplayFrameSource(tmp_path)


def test_command_prints_one_line_per_frame(tmp_path, capsys):
    for name in ["a.png", "b.png"]:
        _write(tmp_path, name, size=(100, 50))
    main([str(tmp_path), "--region", "0", "0", "40", "10"])
    assert capsys.readouterr().out.splitlines() == ["   0.000s  40x10", "   0.250s  40x10"]

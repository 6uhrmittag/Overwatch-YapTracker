import json

from yaptracker import config
from yaptracker.capture.source import Region


def test_uncalibrated_windows_use_the_default_box(tmp_path):
    path = tmp_path / "config.json"
    assert config.chat_region(2560, 1440, path) == Region(55, 510, 615, 395)
    assert config.saved_chat_boxes(path) == {}


def test_a_box_drawn_at_one_size_scales_to_every_size_of_that_ratio(tmp_path):
    path = tmp_path / "config.json"
    config.save_chat_region(2560, 1440, Region(50, 500, 700, 420), path)
    assert config.chat_region(2560, 1440, path) == Region(50, 500, 700, 420)
    assert config.chat_region(1920, 1080, path) == Region(38, 375, 525, 315)
    assert list(config.saved_chat_boxes(path)) == ["16:9"]
    assert config.saved_chat_boxes(path)["16:9"].calibrated_at == (2560, 1440)


def test_old_pixel_regions_are_converted_once(tmp_path):
    path = tmp_path / "config.json"
    old = {"chat_regions": {"2560x1440": {"x": 50, "y": 500, "width": 700, "height": 420}}}
    path.write_text(json.dumps(old))
    assert config.chat_region(2560, 1440, path) == Region(50, 500, 700, 420)
    saved = json.loads(path.read_text())
    assert "chat_regions" not in saved and saved["chat_boxes"]["16:9"]["calibrated_at"] == [
        2560,
        1440,
    ]


def test_a_new_window_size_asks_for_one_check(tmp_path):
    path = tmp_path / "config.json"
    assert not config.size_needs_check(1920, 1080, path)  # never calibrated: nothing to re-check
    config.save_chat_region(2560, 1440, Region(50, 500, 700, 420), path)
    assert not config.size_needs_check(2560, 1440, path)
    assert config.size_needs_check(1920, 1080, path)
    assert config.size_needs_check(3440, 1440, path)  # another ratio: default box, worth a look
    config.mark_size_checked(1920, 1080, path)
    assert not config.size_needs_check(1920, 1080, path)


def test_aspect_ratio_keys():
    assert config.aspect(2560, 1440) == config.aspect(1920, 1080) == "16:9"
    assert config.aspect(3440, 1440) == "43:18"

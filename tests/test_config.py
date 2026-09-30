from yaptracker import config
from yaptracker.capture.source import Region


def test_unsaved_resolution_uses_the_default_box(tmp_path):
    path = tmp_path / "config.json"
    assert config.chat_region(2560, 1440, path) == Region(55, 510, 615, 395)
    assert config.saved_chat_regions(path) == {}


def test_regions_are_saved_per_resolution(tmp_path):
    path = tmp_path / "config.json"
    config.save_chat_region(2560, 1440, Region(50, 500, 700, 420), path)
    config.save_chat_region(1920, 1080, Region(40, 380, 460, 300), path)
    assert config.chat_region(2560, 1440, path) == Region(50, 500, 700, 420)
    assert config.saved_chat_regions(path) == {
        "2560x1440": Region(50, 500, 700, 420),
        "1920x1080": Region(40, 380, 460, 300),
    }

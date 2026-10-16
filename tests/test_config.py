import json
import logging
from pathlib import Path

import numpy as np
import pytest

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


def busy(*_args, **_kwargs):
    raise PermissionError(13, "The process cannot access the file")  # what Windows says (#451)


def test_the_capture_path_never_reads_the_file_again(tmp_path, monkeypatch):
    """#451: on Windows, reading config.json while a save replaces it crashed the capture."""
    from yaptracker.debug import DebugSamples

    path = config.paths.config_file()
    config.save_debug_samples(True)
    samples = DebugSamples(tmp_path / "debug", config.debug_samples)
    monkeypatch.setattr(config, "_read", busy)
    samples.on_signals({"overview": np.zeros((36, 64, 3), np.uint8)})  # no PermissionError
    assert config.debug_samples() and config.hotkeys()["pause"] == ""
    assert config.read_every_s() == config.READ_GAPS[0] and path.exists()


def test_a_busy_file_is_tried_again(tmp_path, monkeypatch):
    path, real_replace, tries = tmp_path / "config.json", Path.replace, []

    def replace(self, target):
        tries.append(target)
        if len(tries) < 3:
            busy()
        return real_replace(self, target)

    monkeypatch.setattr(config, "RETRY_WAITS_S", (0, 0, 0))
    monkeypatch.setattr(Path, "replace", replace)
    config.save_window_place({"x": 1}, path)
    assert len(tries) == 3 and json.loads(path.read_text())["window"] == {"x": 1}


def test_a_save_that_keeps_failing_never_fails_the_caller(tmp_path, monkeypatch, caplog):
    path = tmp_path / "config.json"
    caplog.set_level(logging.INFO, "yaptracker.config")
    monkeypatch.setattr(config, "RETRY_WAITS_S", (0,))
    with monkeypatch.context() as locked:
        locked.setattr(Path, "replace", busy)
        config.save_window_place({"x": 1}, path)
        config.save_show_callouts(True, path)
        assert config.window_place(path) == {"x": 1} and config.show_callouts(path)  # in memory
    assert caplog.text.count("couldn't save config.json") == 1  # logged once, not per save
    config.save_line_pictures(False, path)  # the file is free again: everything lands on disk
    saved = json.loads(path.read_text())
    assert saved["window"] == {"x": 1} and saved["show_callouts"] and "saved again" in caplog.text


@pytest.mark.parametrize("text", ["", '{"window": {"x": 1', "null", "\x00\x00\x00"])
def test_a_broken_settings_file_is_kept_aside_and_the_defaults_start(tmp_path, text, caplog):
    """#456: half-written after a power cut, YapTracker crashed at every start."""
    path = tmp_path / "config.json"
    path.write_text(text, encoding="utf-8")
    assert config.setup_state(path) is None and config.update_check(path) is True
    (kept,) = tmp_path.glob("config.broken-*.json")
    assert kept.read_text(encoding="utf-8") == text and not path.exists()
    assert config.broken == kept and "was broken" in caplog.text
    config.save_show_callouts(True, path)  # the next save writes a good file again
    assert json.loads(path.read_text()) == {"show_callouts": True}


def test_a_save_is_on_disk_before_it_replaces_the_file(tmp_path, monkeypatch):
    synced = []
    monkeypatch.setattr(config.os, "fsync", lambda fd: synced.append(fd))
    config.save_show_callouts(True, tmp_path / "config.json")
    assert len(synced) == 1


def test_a_broken_file_that_cant_be_moved_still_starts_and_never_overwrites_an_older_one(
    tmp_path, monkeypatch
):
    path = tmp_path / "config.json"
    path.write_text("{", encoding="utf-8")
    monkeypatch.setattr(config.time, "strftime", lambda fmt: "20261016-220000")
    (tmp_path / "config.broken-20261016-220000.json").write_text("older", encoding="utf-8")
    assert config.update_check(path) is True  # moved aside next to the older one
    assert (tmp_path / "config.broken-20261016-220000.json").read_text() == "older"
    assert (tmp_path / "config.broken-20261016-220000-1.json").read_text() == "{"
    config.forget()
    path.write_text("{", encoding="utf-8")
    monkeypatch.setattr(config.Path, "replace", lambda self, target: busy())  # open elsewhere
    assert config.update_check(path) is True and config.broken == path  # starts anyway

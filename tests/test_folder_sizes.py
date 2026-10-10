"""Folder sizes without walking (#387): counted once at start, then kept up to date."""

import logging
from pathlib import Path

import numpy as np
import pytest
from nicegui.testing import User, user_simulation

from yaptracker import runtime, sizes
from yaptracker.capture.source import Region
from yaptracker.debug import DebugSamples, folder_size
from yaptracker.lines import LinePictures, pictures_in
from yaptracker.ui import shell, timing

from .test_debug import Clock, signals

OCT = 1_790_000_000.0  # 2026-09
NOV = OCT + 40 * 86400


def on_disk_pictures(folder: Path) -> int:
    return sum(size for _, size in pictures_in(folder))


def test_picture_sizes_stay_right_after_writes_overwrites_and_clean_ups(tmp_path):
    folder = tmp_path / "lines"
    old = LinePictures(folder)
    old.start(background=False)
    chat = np.random.default_rng(1).integers(0, 255, (300, 600, 3), dtype=np.uint8)
    for n in range(4):
        old.save(n, OCT, chat, Region(0, 20 * n, 600, 20))
    pictures = LinePictures(folder, cap_bytes=on_disk_pictures(folder) + 100)
    assert pictures.size_bytes() is None  # not counted yet: unknown, not 0
    pictures.start(background=False)
    assert pictures.size_bytes() == on_disk_pictures(folder)
    pictures.save(1, OCT, chat, Region(0, 0, 600, 60))  # a better reading, bigger: over it
    pictures.save(9, NOV, chat, Region(0, 0, 600, 30))  # over the cap: September goes
    assert pictures.size_bytes() == on_disk_pictures(folder)
    assert [p.name for p in folder.iterdir()] == ["2026-10"]


def test_debug_sizes_stay_right_after_samples_corrections_and_clean_ups(tmp_path):
    clock = Clock()
    folder = tmp_path / "debug"
    samples = DebugSamples(folder, lambda: True, clock)
    samples.start(background=False)
    for _ in range(3):
        samples.on_signals(signals())
        clock.now += 5
        samples.match_event("end")
    assert samples.size_bytes() == folder_size(folder)
    capped = DebugSamples(folder, lambda: True, clock, cap_bytes=samples.size_bytes() - 1)
    capped.start(background=False)  # the oldest sample goes
    assert capped.size_bytes() == folder_size(folder) and len(list(folder.rglob("*-end"))) == 2


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_settings_never_walks_a_folder(user: User, monkeypatch, tmp_path, caplog):
    pictures, debug = LinePictures(tmp_path / "lines"), DebugSamples(tmp_path / "d", lambda: True)
    pictures.start(background=False)
    debug.start(background=False)
    monkeypatch.setattr(runtime, "pictures", pictures)
    monkeypatch.setattr(runtime, "debug", debug)

    def no_walking(*args, **kwargs):
        raise AssertionError("Settings walked a folder")

    monkeypatch.setattr(Path, "rglob", no_walking)
    monkeypatch.setattr(timing, "SLOW_MS", 0)  # every render says how long it took
    caplog.set_level(logging.INFO, "yaptracker.ui.timing")
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("Line pictures: 0.0 MB of 2 GB")
    line = next(r.getMessage() for r in caplog.records if "ui: settings took" in r.getMessage())
    assert "pictures" in line and "debug" in line


def test_a_count_doesnt_undo_what_was_written_meanwhile():
    tally = sizes.FolderSizes()
    tally.set(Path("a/1.webp"), 500)  # written while the start walk ran: newer than the walk
    assert tally.total() is None
    tally.counted([(Path("a/1.webp"), 100), (Path("a/2.webp"), 200)])
    assert tally.total() == 700
    assert tally.drop(Path("a")) == 700 and tally.total() == 0

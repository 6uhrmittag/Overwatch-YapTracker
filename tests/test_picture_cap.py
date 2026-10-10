"""How much space line pictures may take (#389): a slider from 50 MB to 5 GB, 2 GB by default."""

import os

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.lines import LinePictures
from yaptracker.ui import shell

MB = 1_000_000


def pictures_of(folder, sizes):
    """Sparse files: their size counts, the disk stays empty."""
    for month, size in sizes.items():
        (folder / month).mkdir(parents=True)
        with open(folder / month / "1.webp", "wb") as f:
            os.truncate(f.fileno(), size)
    pictures = LinePictures(folder, cap_bytes=config.picture_cap_mb() * MB)
    pictures.start(background=False)
    return pictures


def months(folder):
    return sorted(p.name for p in folder.iterdir())


def test_two_gigabytes_unless_set():
    assert config.picture_cap_mb() == 2000
    config.save_picture_cap_mb(250)
    assert config.picture_cap_mb() == 250


def test_what_a_lower_limit_would_free_without_walking(tmp_path):
    pictures = pictures_of(tmp_path, {"2026-08": 1000, "2026-09": 1000, "2026-10": 1000})
    assert pictures.would_free(1500) == (2000, "2026-10")
    assert pictures.would_free(3000) == (0, "2026-08")  # all fit: nothing goes
    assert pictures.would_free(500) == (3000, None)  # every month


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def open_settings(user, monkeypatch, folder):
    folder.mkdir()
    pictures = pictures_of(folder, {"2026-08": 30 * MB, "2026-09": 30 * MB, "2026-10": 40 * MB})
    monkeypatch.setattr(runtime, "pictures", pictures)
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("Line pictures: 100.0 MB of 2 GB")
    return next(iter(user.find(marker="pictures-cap").elements))


async def test_lowering_says_what_it_frees_then_frees_it_oldest_first(user, monkeypatch, tmp_path):
    slider = await open_settings(user, monkeypatch, tmp_path / "lines")
    slider.set_value(0)  # dragged to 50 MB: nothing deleted yet
    await user.should_see("Keep up to 50 MB")
    await user.should_see("Frees 60.0 MB: the pictures before October 2026 go.")
    assert months(tmp_path / "lines") == ["2026-08", "2026-09", "2026-10"]
    user.find(marker="pictures-cap").trigger("change")  # released
    await user.should_see("Freed 60.0 MB: the pictures before October 2026 are gone.")
    assert months(tmp_path / "lines") == ["2026-10"] and config.picture_cap_mb() == 50
    await user.should_see("Line pictures: 40.0 MB of 50 MB")


async def test_raising_deletes_nothing(user: User, monkeypatch, tmp_path):
    slider = await open_settings(user, monkeypatch, tmp_path / "lines")
    slider.set_value(8)
    await user.should_see("Keep up to 5 GB")
    user.find(marker="pictures-cap").trigger("change")
    await user.should_see("Line pictures: 100.0 MB of 5 GB")
    assert months(tmp_path / "lines") == ["2026-08", "2026-09", "2026-10"]
    assert config.picture_cap_mb() == 5000 and runtime.pictures.cap_bytes == 5000 * MB

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
    assert pictures.would_free(1500) == (2000, "2026-10", True, False)
    assert pictures.would_free(3000) == (0, "2026-08", False, False)  # all fit: nothing goes
    # never the month being written (#462): its one picture is its newest, so it stays
    assert pictures.would_free(500) == (2000, "2026-10", True, False)


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


async def test_a_limit_below_this_month_says_only_its_oldest_go(user, monkeypatch, tmp_path):
    """#462: 50 MB with a busy month: this month loses its oldest pictures, never all of them."""
    folder = tmp_path / "lines"
    (folder / "2026-10").mkdir(parents=True)
    for n, size in [(1, 30), (2, 20), (3, 20), (4, 20)]:  # this month: 90 MB
        with open(folder / "2026-10" / f"{n}.webp", "wb") as f:
            os.truncate(f.fileno(), size * MB)
    pictures = LinePictures(folder, cap_bytes=2000 * MB)
    pictures.start(background=False)
    monkeypatch.setattr(runtime, "pictures", pictures)
    await user.open("/")
    user.find(marker="nav-settings").click()
    slider = next(iter(user.find(marker="pictures-cap").elements))
    slider.set_value(0)
    await user.should_see("Frees 50.0 MB: the oldest since October 2026 go.")
    user.find(marker="pictures-cap").trigger("change")
    await user.should_see("Freed 50.0 MB: the oldest since October 2026 are gone.")
    assert sorted(p.name for p in (folder / "2026-10").iterdir()) == ["3.webp", "4.webp"]

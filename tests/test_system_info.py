"""System info in the log and in Settings -> About (#214): format, re-logging, no names."""

import logging

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, gpu, system_info
from yaptracker.system_info import Display, game_line
from yaptracker.ui import shell


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(system_info, "_machine", None)
    monkeypatch.setattr(system_info, "_game", None)
    monkeypatch.setattr(system_info, "_settings", None)
    monkeypatch.setattr(system_info, "windows", lambda: "Windows 11 Pro 24H2 (build 26100.4061)")
    monkeypatch.setattr(
        system_info, "cpu", lambda: "Intel(R) Core(TM) i7-13700K, 16 cores / 24 threads"
    )
    monkeypatch.setattr(system_info, "ram", lambda: "32 GB")
    monkeypatch.setattr(config, "on_save", [system_info.log_settings])


def test_the_start_block(monkeypatch, caplog):
    cards = [gpu.Adapter(0, "NVIDIA GeForce RTX 4090", 24 * 1024**3),
             gpu.Adapter(1, "AMD Radeon(TM) Graphics", 512 * 1024**2),
             gpu.Adapter(2, "NVIDIA GeForce RTX 4090", 24 * 1024**3)]  # fmt: skip
    monkeypatch.setattr(gpu, "adapters", lambda: cards)
    with caplog.at_level(logging.INFO, logger="yaptracker.system_info"):
        system_info.log_at_start()
    assert [r.getMessage() for r in caplog.records] == [
        "system: YapTracker v0.0.0.dev0 | Windows 11 Pro 24H2 (build 26100.4061)",
        "system: CPU Intel(R) Core(TM) i7-13700K, 16 cores / 24 threads | RAM 32 GB",
        "system: GPU 0 NVIDIA GeForce RTX 4090 (24 GB) | GPU 1 AMD Radeon(TM) Graphics (iGPU)",
        "system: settings: OCR RapidOCR, Competitive light, other best, read every 1.5 s, "
        "debug samples on",
    ]  # the same card listed twice by Windows counts once


def test_the_display_line():
    assert game_line(Display(3840, 2160, 240, True), 3840, 2160, "borderless") == (
        "display of Overwatch: 3840x2160 @ 240 Hz, HDR on | Overwatch window 3840x2160 borderless"
    )
    assert game_line(Display(2560, 1440, 165, None), 1920, 1080, "windowed").startswith(
        "display of Overwatch: 2560x1440 @ 165 Hz, HDR unknown | Overwatch window 1920x1080"
    )


def test_settings_are_logged_again_when_they_change(caplog):
    with caplog.at_level(logging.INFO, logger="yaptracker.system_info"):
        system_info.log_settings()
        config.save_read_every_s(3.0)
        config.save_read_every_s(3.0)  # saved again, unchanged: no new line
        config.save_debug_samples(False)
        config.save_identity(["Pickle"], ["Waffle"])  # not a setting of the line: no new line
    assert [r.getMessage().split("settings: ")[1] for r in caplog.records] == [
        "OCR RapidOCR, Competitive light, other best, read every 1.5 s, debug samples on",
        "OCR RapidOCR, Competitive light, other best, read every 3 s, debug samples on",
        "OCR RapidOCR, Competitive light, other best, read every 3 s, debug samples off",
    ]


def test_no_names_in_it():
    config.save_identity(["Pickle"], ["Waffle"])
    system_info.game_found(None, 2560, 1440)
    text = "\n".join(system_info.summary())
    assert "Pickle" not in text and "Waffle" not in text


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_about_shows_it_with_a_copy_button(user: User):
    config.save_setup_state("done")
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("CPU Intel(R) Core(TM) i7-13700K, 16 cores / 24 threads | RAM 32 GB")
    await user.should_see("display of Overwatch: not found yet")
    user.find(marker="copy-system").click()
    await user.should_see("Copied. Paste it into a chat.")

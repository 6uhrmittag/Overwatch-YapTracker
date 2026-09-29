"""The window: icon rail and view switching, via NiceGUI's simulated user (no browser)."""

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import __version__
from yaptracker.ui import shell


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_opens_on_live(user: User):
    await user.open("/")
    await user.should_see("Live")
    await user.should_see("No yaps yet. Suspiciously quiet lobby.")


@pytest.mark.parametrize(
    ("key", "text"),
    [
        ("yappers", "Yappers"),
        ("sessions", "Sessions"),
        ("search", "Search"),
        ("settings", "Settings"),
        ("live", "This match"),
    ],
)
async def test_rail_switches_views(user: User, key: str, text: str):
    await user.open("/")
    user.find(marker=f"nav-{key}").click()
    await user.should_see(text)
    assert "is-active" in user.find(marker=f"nav-{key}").elements.pop().classes


async def test_settings_shows_version(user: User):
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see(f"YapTracker {__version__}")


def test_rail_has_all_five_views():
    assert [v.label for v in shell.VIEWS] == ["Live", "Yappers", "Sessions", "Search", "Settings"]

"""Live's "What I see" (#163): hidden by default, remembered, opens by itself only when it helps."""

import numpy as np
import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.capture.source import Frame, Region
from yaptracker.capture.watcher import CaptureWatcher
from yaptracker.ui import shell


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


@pytest.fixture
def capturing(monkeypatch):
    config.save_setup_state("done")
    watcher = CaptureWatcher(lambda: None, lambda _: None)
    watcher.state, watcher.frames = "capturing", 1
    watcher.last_frame = Frame(0.0, np.zeros((395, 615, 3), np.uint8))
    monkeypatch.setattr(runtime, "watcher", watcher)
    return watcher


def preview(user):
    (card,) = user.find(marker="preview").elements
    (picture,) = [e for e in card.descendants() if isinstance(e, ui.image)]
    return card, picture


async def test_hidden_means_no_pictures_are_sent(user: User, capturing):
    await user.open("/")
    await user.should_see("Listening for yaps")
    card, picture = preview(user)
    assert "yt-hidden" in card.classes and not picture.source
    await user.should_see("Show what I see")


async def test_the_choice_is_remembered(user: User, capturing):
    config.save_show_what_i_see(True)
    await user.open("/")
    await user.should_see("Chat box 615 × 395 px, 1 frames")
    await user.should_see("Hide what I see")
    card, picture = preview(user)
    assert "yt-hidden" not in card.classes and picture.source


async def test_opens_by_itself_when_the_chat_box_needs_a_look(user: User, capturing, monkeypatch):
    config.save_chat_region(2560, 1440, Region(55, 510, 615, 395))
    monkeypatch.setattr(runtime, "window_size", (3840, 2160))  # drawn at 1440p, now 4K
    await user.open("/")
    await user.should_see("Overwatch runs at 3840\u00d72160 now")
    await user.should_see("Chat box 615 × 395 px, 1 frames")
    user.find(marker="preview-hide").click()
    card, _ = preview(user)
    assert "yt-hidden" in card.classes  # and it stays closed while the hint is still up
    assert not config.show_what_i_see()

"""Live's refresh in named steps (#311): the state of the pill, the orange banner's words, the
size hint and a snap's title, on their own. The Live view's own tests cover the page."""

import time
from types import SimpleNamespace

from yaptracker import runtime
from yaptracker.matches import Status
from yaptracker.ui.views import _capture_now, health_words, live_state, size_words, snap_title


def test_the_pill_says_one_thing_paused_first():
    assert live_state(True, True, "lost", True) == "paused"
    assert live_state(False, True, "lost", True) == "trouble"
    assert live_state(False, False, "reconnecting", True) == "reconnecting"
    assert live_state(False, False, None, True) == "listening"
    assert live_state(False, False, None, False) == "waiting"


def test_the_banner_says_what_covers_the_chat_box_before_anything_else():
    gap = SimpleNamespace(since=time.mktime((2026, 11, 22, 20, 5, 0, 0, 0, -1)), reason="crash")
    assert health_words(None, False, None, None) is None
    assert health_words("File Explorer", True, gap, None).startswith(
        "Another window covers Overwatch's chat box (File Explorer)")  # fmt: skip
    said = health_words(None, True, gap, "  device lost  ")
    assert said.startswith("Not recording since 20:05 (capture stopped). Windows says:")
    assert "“device lost”" in said and said.endswith("shows why.")
    assert "Windows says" not in health_words(None, True, gap, "   ")  # nothing to quote


def test_a_covering_window_makes_a_short_loss_a_real_one(monkeypatch):
    health = SimpleNamespace(gap="gap", state=lambda: "reconnecting")
    monkeypatch.setattr(runtime, "health", health)
    watcher = SimpleNamespace(state="capturing", covered="Notepad")
    assert _capture_now(watcher) == (True, "Notepad", "gap", "lost")
    watcher.covered = None
    assert _capture_now(watcher) == (True, None, "gap", "reconnecting")
    monkeypatch.setattr(runtime, "health", None)
    assert _capture_now(None) == (False, None, None, None)


def test_size_and_snap_words():
    assert size_words((1920, 1080)).startswith("Overwatch runs at 1920×1080 now.")
    day = time.mktime((2026, 11, 22, 20, 0, 0, 0, 0, -1))
    assert snap_title(None, None, day) == "Live · Sun Nov 22, 2026"
    where = Status(1, 3, day, map_name="ilios", mode="UNRANKED")
    assert snap_title(where, day, day + 9) == "Match 3 on Ilios · Unranked · Sun Nov 22, 2026"

"""The capture wiring split out of app.py (#311): its small decisions, and the steps that pick the
capture source, follow the black-window fallback and end an evening. Fakes, no Windows."""

from types import SimpleNamespace

import numpy as np
import pytest

from yaptracker import capture_wiring, runtime, system_info
from yaptracker.capture import gdi, stats, wgc
from yaptracker.capture.source import Frame, Region
from yaptracker.capture.watcher import MATCH_STALL_S, STALL_S
from yaptracker.capture_wiring import (
    CaptureWiring,
    cpu_state_words,
    fps_state_words,
    game_ran_for,
    in_match,
    in_match_or_unknown,
    screen_match,
    stall_limit,
)

RUNNING, ENDED = (
    SimpleNamespace(running=True, match_id=7),
    SimpleNamespace(running=False, match_id=7),
)


def test_without_a_match_tracker_the_box_counts_as_in_a_match_but_signals_dont():
    assert not in_match(None) and in_match_or_unknown(None)
    assert in_match(RUNNING) and in_match_or_unknown(RUNNING)
    assert not in_match(ENDED) and not in_match_or_unknown(ENDED)


def test_the_words_of_the_fps_and_cpu_lines():
    assert fps_state_words(False, True) == "running, in match"
    assert fps_state_words(True, False) == "paused, between matches"
    assert cpu_state_words(False, True, True) == "no game"
    assert cpu_state_words(True, True, True) == "paused"
    assert cpu_state_words(True, False, True) == "in match"
    assert cpu_state_words(True, False, False) == "between matches"


def test_a_short_stall_limit_only_in_a_match_with_overwatch_in_front():
    assert stall_limit(True, True) == MATCH_STALL_S
    assert stall_limit(True, False) == stall_limit(False, True) == STALL_S


def test_the_screen_fallback_sees_the_running_match_only():
    assert screen_match(RUNNING) == 7 and screen_match(ENDED) is None and screen_match(None) is None


def test_how_long_the_game_ran_before_us():
    assert game_ran_for(None, 100.0) is None
    assert game_ran_for(40.0, 100.0) == 60.0 and game_ran_for(200.0, 100.0) == 0.0  # clock skew


class FakeScreen:
    def __init__(self, screen=False, check=False):
        self.screen, self._check, self.calls = screen, check, []

    def opening(self):
        self.calls.append("opening")

    def check(self, window_capture, match):
        self.calls.append(("check", window_capture, match))
        return self._check

    def stalled(self):
        self.calls.append("stalled")

    def game_closed(self):
        self.calls.append("game_closed")


class FakeSource:
    def __init__(self, hwnd, region_for, signals_for=None, fps=None, quiet=None):
        self.hwnd, self.region_for, self.fps, self.quiet = hwnd, region_for, fps, quiet


@pytest.fixture
def wiring(monkeypatch):
    for name in ("changes", "black", "screen", "watcher", "matches", "window_size", "debug",
                 "evenings"):  # fmt: skip
        monkeypatch.setattr(runtime, name, getattr(runtime, name, None))  # restored afterwards
    monkeypatch.setattr(runtime, "matches", None)
    monkeypatch.setattr(runtime, "debug", None)
    monkeypatch.setattr(stats.CAPTURE, "how", stats.CAPTURE.how)  # open_source sets it
    w = CaptureWiring(dev=False)
    monkeypatch.setattr(wgc, "WgcFrameSource", FakeSource)
    monkeypatch.setattr(gdi, "GdiFrameSource", FakeSource)
    monkeypatch.setattr(system_info, "game_found", lambda *args: found.append(args))
    found: list = []
    w.games_found = found
    return w


@pytest.mark.parametrize(("build", "screen", "window"), [(26100, False, True), (26100, True, False),
                                                         (19045, False, False)])  # fmt: skip
def test_the_window_is_captured_where_windows_can_and_it_isnt_black(
    wiring, monkeypatch, build, screen, window
):
    monkeypatch.setattr(wgc, "windows_build", lambda: build)
    runtime.screen = FakeScreen(screen=screen)
    source = wiring.open_source(42)
    assert wiring.found["window_capture"] is window and runtime.screen.calls == ["opening"]
    assert (source.fps is not None) is window  # the window at a rate; the screen grabs quietly
    assert (source.quiet is not None) is (not window)


def test_the_first_picture_of_a_window_says_where_the_game_is_once(wiring, monkeypatch):
    monkeypatch.setattr(wgc, "windows_build", lambda: 26100)
    runtime.screen = FakeScreen()
    wiring.open_source(42)
    box = wiring.region_for(2560, 1440)
    wiring.region_for(2560, 1440)
    assert wiring.games_found == [(42, 2560, 1440)] and runtime.window_size == (2560, 1440)
    assert isinstance(box, Region)


def test_a_black_window_reopens_the_capture_and_failing_restarts_only_switch_a_window(wiring):
    reopened = []
    runtime.watcher = SimpleNamespace(reopen=lambda: reopened.append(1), window=None)
    runtime.matches = RUNNING
    runtime.screen = FakeScreen(check=True)
    wiring.found["window_capture"] = True
    overview = np.zeros((4, 4, 3), np.uint8)
    wiring.on_signals(Frame(0.0, overview, {"overview": overview}))
    assert runtime.screen.calls == [("check", True, 7)] and reopened == [1]
    wiring.capture_failing(42)
    wiring.found["window_capture"] = False  # GDI already: nothing else to switch to
    wiring.capture_failing(42)
    assert runtime.screen.calls.count("stalled") == 1


def test_overwatch_closing_forgets_how_long_it_ran(wiring):
    runtime.screen = FakeScreen()
    wiring.ran_before = 3600.0
    wiring.evening_over()
    assert wiring.ran_before == 0.0 and runtime.screen.calls == ["game_closed"]


def test_the_stall_limit_follows_the_match_and_the_focus(wiring, monkeypatch):
    runtime.matches = RUNNING
    monkeypatch.setattr(wiring, "overwatch_in_front", lambda: True)
    assert wiring.stall_s() == MATCH_STALL_S
    runtime.matches = ENDED
    assert wiring.stall_s() == STALL_S


def test_dev_mode_plays_the_demo(monkeypatch):
    monkeypatch.setattr(runtime, "window_size", None)
    for name in ("changes", "black", "screen"):
        monkeypatch.setattr(runtime, name, getattr(runtime, name, None))
    watcher = CaptureWiring(dev=True).make_watcher()
    assert runtime.window_size == (2560, 1440) and watcher.state == "waiting"
    assert capture_wiring.CaptureWatcher is type(watcher)


class FakeReader:
    def __init__(self, reread=False):
        self.offered, self.kept, self.reread = [], [], reread

    def offer(self, image, mode):
        self.offered.append(mode)

    def wants_reread(self):
        return self.reread

    def keep_for_tidy(self, image):
        self.kept.append(1)


@pytest.mark.parametrize(
    ("mode", "changed", "reread", "offered", "kept"),
    [
        ("after", True, False, ["after"], 0),  # read after the match: changed frames wait
        ("after", False, True, [], 0),  # ... and nothing is read again now
        ("best", False, False, [], 0),  # nothing new: nothing to read
        ("best", False, True, ["best"], 0),  # weak lines on screen: read again (#195)
        ("light", True, False, ["light"], 1),  # light now, the best later when idle (#336)
    ],
)
def test_the_chat_path_by_reading_mode(wiring, monkeypatch, mode, changed, reread, offered, kept):
    reader = FakeReader(reread)
    monkeypatch.setattr(runtime, "reader", reader)
    monkeypatch.setattr(runtime, "reading", SimpleNamespace(now=lambda: mode, light_problem=None))
    monkeypatch.setattr(wiring.changes, "update", lambda image, scale: changed)
    wiring.on_frame(Frame(0.0, np.zeros((4, 4, 3), np.uint8)))
    assert reader.offered == offered and len(reader.kept) == kept


def test_dev_mode_starts_capture_without_hotkeys(monkeypatch):
    from nicegui import app

    for name in ("changes", "black", "screen"):
        monkeypatch.setattr(runtime, name, getattr(runtime, name, None))
    started, stopped = [], []
    monkeypatch.setattr(app, "on_startup", started.append)
    monkeypatch.setattr(app, "on_shutdown", stopped.append)
    monkeypatch.setattr(capture_wiring, "install_hotkeys", lambda: started.append("hotkeys"))
    monkeypatch.setattr(capture_wiring.CPU, "state", capture_wiring.CPU.state)  # restored
    wiring = CaptureWiring(dev=True)
    wiring.install()
    assert wiring.start_capture in started and wiring.stop_capture in stopped
    assert "hotkeys" not in started and capture_wiring.CPU.state == wiring.cpu_state


@pytest.mark.parametrize("until", [0.0, 50.0, 1e12], ids=["off", "evening over", "recording"])
def test_the_chat_recorder_on_or_off_never_stops_the_capture(wiring, monkeypatch, tmp_path, until):
    """#663: the recorder's CPU.part crashed every capture start, with it off too. The real
    recorder and the real CPU counter, through on_signals and on_frame."""
    from yaptracker.recorder import ChatRecorder

    recorder = ChatRecorder(tmp_path, until=lambda: until, clock=lambda: 100.0,
                            free=lambda folder: 10**12)  # fmt: skip
    monkeypatch.setattr(runtime, "recorder", recorder)
    monkeypatch.setattr(runtime, "pause", SimpleNamespace(paused=False))
    monkeypatch.setattr(runtime, "reader", FakeReader())
    monkeypatch.setattr(runtime, "reading", SimpleNamespace(now=lambda: "best", light_problem=None))
    monkeypatch.setattr(wiring.changes, "update", lambda image, scale: True)
    runtime.screen = FakeScreen()
    crop = np.zeros((4, 4, 3), np.uint8)
    wiring.on_signals(Frame(0.0, crop, {"overview": crop, "banner": crop}))
    wiring.on_frame(Frame(0.0, crop))
    assert runtime.screen.calls == [("check", False, None)]  # on_signals ran to its end
    assert runtime.reader.offered == ["best"]

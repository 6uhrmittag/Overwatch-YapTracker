"""Windows 10 (#216): capture settings only as far as this Windows can do them, our own 4 fps
gate before the frame is touched, and "recording again" only after a real frame. Fakes."""

import logging
import sys
import types

import numpy as np
import pytest

from yaptracker.capture import stats as stats_module
from yaptracker.capture import wgc
from yaptracker.capture.health import CaptureHealth
from yaptracker.capture.source import Region
from yaptracker.capture.wgc import capture_options
from yaptracker.store.repo import Store


def test_settings_follow_the_windows_build():
    assert capture_options(19045, 4) == ({"cursor_capture": False}, ["draw_border",
                                         "minimum_update_interval"])  # fmt: skip  # 10 22H2
    assert capture_options(20348, 4)[1] == ["minimum_update_interval"]  # Server 2022
    assert capture_options(26100, 4) == ({"cursor_capture": False, "draw_border": False,
                                          "minimum_update_interval": 250}, [])  # fmt: skip
    assert capture_options(17763, 4)[0] == {}  # 1809: none of them


class FakeCapture:
    made: list = []
    refuse: set = set()

    def __init__(self, **options):
        self.options, self.handlers = options, {}
        FakeCapture.made.append(self)

    def event(self, handler):
        self.handlers[handler.__name__] = handler
        return handler

    def start_free_threaded(self):
        if self.refuse & self.options.keys():
            raise RuntimeError("Setting a minimum update interval is not supported")
        return types.SimpleNamespace(is_finished=lambda: True, stop=lambda: None)


class Frame:
    width, height = 64, 36
    frame_buffer = np.zeros((36, 64, 4), np.uint8)


@pytest.fixture
def fake_wgc(monkeypatch):
    FakeCapture.made, FakeCapture.refuse = [], set()
    monkeypatch.setitem(sys.modules, "windows_capture",
                        types.SimpleNamespace(WindowsCapture=FakeCapture))  # fmt: skip
    monkeypatch.setattr(wgc, "CAPTURE", stats_module.CaptureStats())
    return FakeCapture


def test_windows_10_never_gets_the_settings_it_lacks(fake_wgc, monkeypatch, caplog):
    monkeypatch.setattr(wgc, "windows_build", lambda: 19045)
    with caplog.at_level(logging.INFO, logger="yaptracker.capture.wgc"):
        wgc.WgcFrameSource(1, lambda w, h: Region(0, 0, 8, 8))
    (made,) = fake_wgc.made
    assert made.options == {"window_hwnd": 1, "cursor_capture": False}
    assert wgc.CAPTURE.cannot == ["hide the yellow border", "slow the capture down"]
    assert "can't hide the yellow border, slow the capture down" in caplog.text


def test_a_setting_refused_anyway_means_none_at_all(fake_wgc, monkeypatch):
    monkeypatch.setattr(wgc, "windows_build", lambda: 26100)
    fake_wgc.refuse = {"minimum_update_interval"}
    wgc.WgcFrameSource(1, lambda w, h: Region(0, 0, 8, 8))
    assert [m.options for m in fake_wgc.made][-1] == {"window_hwnd": 1}
    assert len(wgc.CAPTURE.cannot) == 3


def test_frames_faster_than_4_fps_are_let_go_untouched(fake_wgc, monkeypatch):
    monkeypatch.setattr(wgc, "windows_build", lambda: 19045)
    used = []
    source = wgc.WgcFrameSource(1, lambda w, h: used.append(1) or Region(0, 0, 8, 8))
    arrived = fake_wgc.made[0].handlers["on_frame_arrived"]
    clock = {"now": 100.0}
    monkeypatch.setattr(wgc.time, "monotonic", lambda: clock["now"])
    for _ in range(200):  # 2 s of a game at 100 fps
        arrived(Frame(), None)
        clock["now"] += 0.01
    # every 230 ms (the gate is 0.9 x 250 ms, so Windows' own 4 fps pass); the other 191 never
    # had their buffer read
    assert len(used) == 9 and wgc.CAPTURE._minute_skipped == 191
    source.close()


def test_a_gap_ends_without_recording_again_when_the_game_closes(tmp_path, caplog):
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        clock = {"now": 1000.0}
        health = CaptureHealth(store, clock=lambda: clock["now"])
        with caplog.at_level(logging.INFO, logger="yaptracker.capture.health"):
            health.lost("crash")  # the capture never started
            clock["now"] += 124
            health.game_closed()
            health.lost("crash")
            clock["now"] += 30
            health.frame()  # a real picture
        lines = [r.getMessage() for r in caplog.records]
        assert lines[1] == "not recorded, Overwatch is gone after 124 s (crash)"
        assert lines[3] == "recording again after 30 s (crash)"
        assert sum("recording again" in line for line in lines) == 1
    finally:
        store.close()


def test_skipped_frames_count_in_the_rate_not_in_the_cost(caplog):
    clock = {"now": 0.0}
    capture = stats_module.CaptureStats(clock=lambda: clock["now"])
    with caplog.at_level(logging.INFO, logger="yaptracker.capture.stats"):
        for i in range(6001):  # 100 fps for a minute, every 25th used
            clock["now"] = i / 100
            if i % 25:
                capture.skipped()
            else:
                capture.frame(0.002)
    (line,) = [r.getMessage() for r in caplog.records]
    assert line == ("capture: 100.0 frames/s from Windows (asked for 4), 2.0 ms per frame here, "
                    "96.0/s of them skipped")  # fmt: skip

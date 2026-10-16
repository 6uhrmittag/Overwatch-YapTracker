"""2 frames a second between matches (#350) and in a match (#115): Windows copies every frame."""

import logging

from yaptracker.capture.wgc import MATCH_FPS, MENU_FPS, CaptureRate


def test_two_frames_a_second_in_and_between_matches_and_no_reopen_for_a_match(caplog):
    caplog.set_level(logging.INFO, "yaptracker.capture.wgc")
    running, reopened = [True], []
    rate = CaptureRate(lambda: running[0], lambda: reopened.append(1))
    assert rate.opened() == MATCH_FPS == 2.0
    assert "asking Windows for 2 frames a second (in a match)" in caplog.text
    running[0] = False  # the end screen: between matches, the same rate
    for _ in range(5):
        rate.check()
    assert reopened == [] and MENU_FPS == 2.0


def test_a_different_rate_reopens_the_capture_once(monkeypatch):
    from yaptracker.capture import wgc

    monkeypatch.setattr(wgc, "MATCH_FPS", 4.0)  # should the rates ever differ again
    running, reopened = [True], []
    rate = CaptureRate(lambda: running[0], lambda: reopened.append(1))
    assert rate.opened() == 4.0
    running[0] = False
    for _ in range(5):  # every frame until the capture is open again
        rate.check()
    assert reopened == [1] and rate.opened() == 2.0


def test_gdi_captures_never_reopen():
    reopened = []
    rate = CaptureRate(lambda: False, lambda: reopened.append(1))
    rate.check()  # no window capture open (GDI on Windows 10, or none yet)
    assert reopened == []

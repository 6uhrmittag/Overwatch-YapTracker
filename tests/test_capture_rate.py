"""2 frames a second between matches, 4 in a match (#350): Windows copies every frame it sends."""

import logging

from yaptracker.capture.wgc import MATCH_FPS, MENU_FPS, CaptureRate


def test_the_capture_opens_at_the_rate_of_the_moment_and_reopens_once_on_a_change(caplog):
    caplog.set_level(logging.INFO, "yaptracker.capture.wgc")
    running, reopened = [True], []
    rate = CaptureRate(lambda: running[0], lambda: reopened.append(1))
    assert rate.opened() == MATCH_FPS == 4.0
    rate.check()
    assert reopened == []  # in a match, still 4
    running[0] = False  # the end screen: between matches
    for _ in range(5):  # every frame until the capture is open again
        rate.check()
    assert reopened == [1]
    assert rate.opened() == MENU_FPS == 2.0
    assert "asking Windows for 2 frames a second (between matches)" in caplog.text


def test_gdi_captures_never_reopen():
    reopened = []
    rate = CaptureRate(lambda: False, lambda: reopened.append(1))
    rate.check()  # no window capture open (GDI on Windows 10, or none yet)
    assert reopened == []

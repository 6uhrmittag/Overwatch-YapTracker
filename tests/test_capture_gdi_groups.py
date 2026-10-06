"""GDI grabs the signal strips in a few rectangles (#319): each BitBlt from the screen makes the
game wait, a strip as long as the whole window. Pure geometry, runs everywhere."""

import numpy as np

from yaptracker.capture.gdi import cut, grab_groups
from yaptracker.capture.source import Region
from yaptracker.game_fps import overlay_regions
from yaptracker.signals import signal_regions


def test_the_real_strips_take_four_grabs_and_every_strip_is_inside_its_grab():
    strips = {**signal_regions(2560, 1440), **overlay_regions(2560, 1440)}
    groups = grab_groups(strips)
    assert len(strips) == 7 and len(groups) == 4
    assert sorted(n for _, names in groups for n in names) == sorted(strips)
    for frame, names in groups:
        for name in names:
            r = strips[name]
            assert frame.x <= r.x and r.x + r.width <= frame.x + frame.width
            assert frame.y <= r.y and r.y + r.height <= frame.y + frame.height


def test_far_apart_strips_stay_apart_and_close_ones_merge():
    strips = {"a": Region(0, 0, 100, 10), "b": Region(0, 12, 100, 10),
              "far": Region(900, 900, 50, 5)}  # fmt: skip
    groups = {tuple(sorted(names)): frame for frame, names in grab_groups(strips)}
    assert groups == {("a", "b"): Region(0, 0, 100, 22), ("far",): Region(900, 900, 50, 5)}


def test_a_strip_is_cut_out_of_its_grab_where_it_was():
    window = np.arange(40 * 60 * 3, dtype=np.uint32).reshape(40, 60, 3)
    frame, part = Region(10, 5, 40, 30), Region(20, 15, 8, 4)
    grabbed = frame.crop(window)
    assert np.array_equal(cut(grabbed, frame, part), part.crop(window))
    assert np.array_equal(cut(window, Region(0, 0, 0, 0), part), part.crop(window))

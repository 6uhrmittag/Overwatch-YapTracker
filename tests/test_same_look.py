"""A signal region that looks the same isn't read again (#453): synthetic strips, fake OCR."""

import numpy as np

from tests.test_signals import strip
from yaptracker.signals import REUSES, SameLook


class Counting:
    def __init__(self, text="ASSEMBLE YOUR TEAM") -> None:
        self.text, self.calls = text, 0

    def __call__(self, image):
        self.calls += 1
        return self.text


def test_the_same_picture_is_read_once():
    read = Counting()
    look = SameLook(read)
    assert look(strip("ASSEMBLE YOUR TEAM")) == "ASSEMBLE YOUR TEAM"
    assert look(strip("ASSEMBLE YOUR TEAM")) == "ASSEMBLE YOUR TEAM"
    assert read.calls == 1 and look.reused == 1


def test_noise_is_the_same_look_new_text_is_not():
    read, rng = Counting(), np.random.default_rng(1)
    look = SameLook(read)
    menu = strip(None)
    look(menu)
    noisy = np.clip(menu.astype(np.int16) + rng.integers(-6, 7, menu.shape), 0, 255)
    look(noisy.astype(np.uint8))  # video noise, a compressed picture
    assert read.calls == 1
    look(strip("ASSEMBLE YOUR TEAM"))  # the banner comes up on the same ground
    assert read.calls == 2


def test_each_region_size_keeps_its_own_reads():
    read = Counting()
    look = SameLook(read)
    look(np.zeros((60, 780, 3), np.uint8))
    look(np.zeros((75, 900, 3), np.uint8))  # another region, the same dark picture
    assert read.calls == 2


def test_an_empty_read_is_tried_again():
    """No OCR yet (the model still loading): the next look reads for real."""
    read = Counting("")
    look = SameLook(read)
    look(strip("VICTORY"))
    read.text = "VICTORY"
    assert look(strip("VICTORY")) == "VICTORY"
    assert read.calls == 2


def test_a_misread_of_a_still_screen_gets_another_chance():
    """Glare on the first look: the still banner is read again after a few kept answers."""
    read = Counting("ASSEM8LE Y0")
    look = SameLook(read)
    banner = strip("ASSEMBLE YOUR TEAM")
    answers = [look(banner)]
    read.text = "ASSEMBLE YOUR TEAM"
    answers += [look(banner) for _ in range(REUSES + 1)]
    assert answers[-1] == "ASSEMBLE YOUR TEAM"
    assert read.calls == 2

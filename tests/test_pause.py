import pytest

from yaptracker.hotkeys import parse
from yaptracker.pause import INTERIM_S, Pause


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_toggle_pauses_and_resumes():
    pause = Pause(Clock())
    pause.toggle()
    assert pause.paused
    pause.toggle()
    assert not pause.paused


def test_a_forgotten_pause_ends_by_itself_after_about_one_match():
    clock = Clock()
    pause = Pause(clock)
    pause.pause()
    clock.now += INTERIM_S - 1
    assert pause.paused and pause.remaining_s() == 1
    clock.now += 1
    assert not pause.paused


def test_the_next_match_ends_the_pause():
    pause = Pause(Clock())
    pause.pause()
    pause.next_match_started()
    assert not pause.paused


def test_hotkey_combos_parse():
    assert parse("Ctrl+Alt+P") == (0x4000 | 0x2 | 0x1, ord("P"))
    assert parse("ctrl + shift + f9") == (0x4000 | 0x2 | 0x4, 0x78)
    with pytest.raises(ValueError):
        parse("Ctrl+Alt+Space")

"""The app window opens where you left it (#253): the rules, without Windows."""

from dataclasses import asdict

from yaptracker import config
from yaptracker.window_place import SETTLE_S, Keeper, Place, visible

LEFT = (0, 0, 2560, 1440)
RIGHT = (2560, 0, 1920, 1080)
ON_RIGHT = Place((2700, 100, 1280, 800), (2700, 100, 1280, 800))


def test_restored_only_while_its_title_bar_is_on_a_screen():
    assert visible(ON_RIGHT, [LEFT, RIGHT])
    assert not visible(ON_RIGHT, [LEFT])  # the second screen was unplugged
    half_off = Place((2000, 100, 1280, 800), (2000, 100, 1280, 800))
    assert visible(half_off, [LEFT])  # 560 of 1280 px off: still grabbable
    above = Place((100, -500, 1280, 800), (100, -500, 1280, 800))
    assert not visible(above, [LEFT, RIGHT])  # title bar above every screen


def test_a_maximised_window_is_checked_where_it_comes_back_to():
    maxed = Place((2552, -8, 1936, 1056), (2700, 100, 1280, 800), maximized=True)
    assert visible(maxed, [LEFT, RIGHT]) and not visible(maxed, [LEFT])


def test_saved_once_it_stopped_moving_and_never_while_minimised():
    clock, seen, saved = [0.0], [ON_RIGHT], []
    keeper = Keeper(lambda: seen[0], saved.append, None, lambda: clock[0])
    keeper.check()  # first sight: wait whether it's still moving
    assert saved == []
    clock[0] += SETTLE_S
    keeper.check()
    assert saved == [ON_RIGHT]
    clock[0] += 5
    keeper.check()
    assert saved == [ON_RIGHT]  # unchanged: not saved again
    seen[0] = None  # minimised
    clock[0] += 5
    keeper.check()
    assert saved == [ON_RIGHT]
    keeper.forget()  # Reset window position
    seen[0] = ON_RIGHT
    keeper.check()
    clock[0] += SETTLE_S
    keeper.check()
    assert saved == [ON_RIGHT, ON_RIGHT]


def test_the_place_survives_config_json(tmp_path):
    path = tmp_path / "config.json"
    config.save_window_place(asdict(ON_RIGHT), path)
    assert Place.from_dict(config.window_place(path)) == ON_RIGHT
    config.save_window_place(None, path)
    assert config.window_place(path) is None
    assert Place.from_dict({"rect": "garbage"}) is None


async def test_settings_can_reset_the_window_position(tmp_path):
    from nicegui.testing import user_simulation

    from yaptracker.ui import shell

    config.save_window_place(asdict(ON_RIGHT))
    config.save_setup_state("done")
    async with user_simulation(root=shell.root) as user:
        await user.open("/")
        user.find(marker="nav-settings").click()
        user.find(marker="reset-window").click()
        await user.should_see("Forgotten. The next start opens at the usual place.")
    assert config.window_place() is None

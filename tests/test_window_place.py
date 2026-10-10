"""The app window opens where you left it (#253): the rules, without Windows."""

from dataclasses import asdict

from yaptracker import config
from yaptracker.window_place import SETTLE_S, Keeper, Monitor, Place, visible

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


# Marv's screens (#299): the 4K main screen, a 1080p one left of it, both with a taskbar.
MAIN_WORK = (0, 0, 3840, 2112)
SECOND_WORK = (-1920, 1080, 1920, 1032)


def test_a_snapped_half_fits_as_it_is():
    """Windows' invisible border sticks out a few px: that's still a fit, nothing moves."""
    from yaptracker.window_place import clamp

    snapped = (-966, 1078, 972, 1038)  # from Marv's config.json
    assert clamp(snapped, [MAIN_WORK, SECOND_WORK]) == snapped


def test_a_window_taller_than_its_screen_is_clamped_with_the_title_bar_inside():
    from yaptracker.window_place import BORDER, clamp

    x, y, w, h = clamp((-1393, 1241, 1300, 1397), [MAIN_WORK, SECOND_WORK])  # Marv's "normal"
    sx, sy, sw, sh = SECOND_WORK
    assert h <= sh + 2 * BORDER and w == 1300
    assert sy - BORDER <= y and y + h <= sy + sh + BORDER  # the top on screen, never above it


def test_off_to_the_side_lands_on_the_nearest_screen():
    from yaptracker.window_place import clamp

    x, y, w, h = clamp((5000, 100, 800, 600), [MAIN_WORK, SECOND_WORK])
    assert (w, h) == (800, 600) and 0 <= x <= 3840 - 800 + 10


def test_the_keeper_never_saves_more_than_fits():
    from yaptracker.window_place import fit

    too_tall = Place((-1393, 1241, 1300, 1397), (-1393, 1241, 1300, 1397))
    clock, saved = [0.0], []
    keeper = Keeper(lambda: too_tall, saved.append, None, lambda: clock[0],
                    fit=lambda p: fit(p, [MAIN_WORK, SECOND_WORK]))  # fmt: skip
    keeper.check()
    clock[0] += SETTLE_S
    keeper.check()
    (place,) = saved
    assert place.rect[3] <= SECOND_WORK[3] + 20 and place.normal[3] <= SECOND_WORK[3] + 20


# Marv's screens as Windows reports them (#365): the 1080p one at 100 %, the 4K main one at 150 %.
SECOND_100 = Monitor((-1920, 1078, 1920, 1080), (-1920, 1078, 1920, 1032), 96)
MAIN_150 = Monitor((0, 0, 3840, 2160), (0, 0, 3840, 2088), 144)


def test_a_snapped_half_on_a_150_percent_screen_fits_with_its_wider_border():
    """At 150 % Windows' invisible border is 11 px, more than 100 %'s allowance (#365)."""
    from yaptracker.window_place import BORDER, border, clamp

    snapped = (1909, 0, 1942, 2099)  # right half of the 4K screen, 11 px border left/right/below
    works, dpis = [MAIN_150.work, SECOND_100.work], [144, 96]
    assert clamp(snapped, works, dpis) == snapped
    assert clamp((-966, 1078, 972, 1038), works, dpis) == (-966, 1078, 972, 1038)
    assert border(96) == BORDER and border(144) >= 12
    sticks_out = (1909, 0, 1942 + 20, 2099)  # really too wide: still clamped
    assert clamp(sticks_out, works, dpis) != sticks_out


def test_the_window_is_born_on_its_saved_screen_in_the_main_screens_units():
    """pywebview multiplies x, y, width, height by the main screen's scaling (#365)."""
    from yaptracker.window_place import birth

    found = [SECOND_100, MAIN_150]
    saved = Place((-966, 1078, 972, 1038), (-1680, 1068, 1690, 1052))  # Marv's config.json
    args = birth(saved, found)
    assert args == {"x": -644, "y": 719, "width": 648, "height": 692}
    physical = [int(args[k] * 1.5) for k in ("x", "y", "width", "height")]
    assert all(abs(a - b) <= 1 for a, b in zip(physical, saved.rect, strict=True))
    same_screen = Place((667, 106, 2042, 1911), (667, 106, 2042, 1911))  # 2026-10-09
    assert birth(same_screen, found) == {"x": 445, "y": 71, "width": 1361, "height": 1274}


def test_no_birth_place_without_a_saved_place_on_a_screen():
    from yaptracker.window_place import birth

    assert birth(None, [SECOND_100, MAIN_150]) == {}
    gone = Place((-966, 1078, 972, 1038), (-966, 1078, 972, 1038))
    assert birth(gone, [MAIN_150]) == {}  # its screen was unplugged
    maxed = Place((-1928, 1070, 1936, 1048), (-1680, 1068, 1690, 1052), maximized=True)
    assert birth(maxed, [SECOND_100, MAIN_150])["x"] == -1120  # born at its un-maximised place

from yaptracker.capture.source import Region
from yaptracker.ui.box_editor import BoxEditor


def editor():
    return BoxEditor(1000, 800, Region(100, 100, 200, 100), grab=10)


def test_drag_inside_moves_the_box():
    e = editor()
    e.press(150, 150)
    e.drag(250, 170)
    e.release()
    assert e.region == Region(200, 120, 200, 100)
    assert not e.dragging


def test_move_stays_inside_the_image():
    e = editor()
    e.press(150, 150)
    e.drag(990, 790)
    assert e.region == Region(800, 700, 200, 100)


def test_drag_a_corner_resizes_against_the_opposite_corner():
    e = editor()
    e.press(302, 198)  # bottom-right corner
    e.drag(400, 300)
    assert e.region == Region(100, 100, 300, 200)
    e.release()
    e.press(98, 102)  # top-left corner
    e.drag(50, 60)
    assert e.region == Region(50, 60, 350, 240)


def test_drag_outside_draws_a_new_box_in_any_direction():
    e = editor()
    e.press(700, 600)
    e.drag(500, 400)
    assert e.region == Region(500, 400, 200, 200)


def test_tiny_boxes_are_ignored():
    e = editor()
    e.press(700, 600)
    e.drag(710, 605)
    assert e.region == Region(100, 100, 200, 100)

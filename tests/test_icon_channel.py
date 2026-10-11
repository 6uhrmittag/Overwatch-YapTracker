"""Channel from the icon (#173): on HDR screens match and team chat come out the same pale
yellow, but the diamond and the three-person icon still tell them apart. Drawn icons here, so
no real screenshot (and no real name) is in the repo."""

import cv2
import numpy as np

from yaptracker import channels
from yaptracker.capture.source import Region
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import parse

H = 36  # text height of a chat line at 4K
PALE = (150, 230, 255)  # BGR: the washed-out yellow both channels get with HDR on


def frame(rows: list[tuple[str | None, str]]) -> tuple[np.ndarray, list[OcrLine]]:
    """A dark chat box; each row: its icon ("diamond", "team" or None) and its text."""
    image = np.full((60 + len(rows) * 50, 900, 3), 12, np.uint8)
    lines = []
    for i, (icon, text) in enumerate(rows):
        x, y = 100, 30 + i * 50
        cx, cy = int(x - 0.85 * H), y + H // 2
        if icon == "diamond":
            r = int(0.2 * H)
            corners = np.array([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)])
            cv2.fillPoly(image, [corners], PALE)
        elif icon == "team":
            for dx in (-12, 0, 12):  # three people: a head and a body each
                cv2.circle(image, (cx + dx, cy - 6), 3, PALE, -1)
                cv2.ellipse(image, (cx + dx, cy + 5), (4, 5), 0, 0, 360, PALE, -1)
        cv2.rectangle(image, (x, y + 8), (x + 12 * len(text), y + H - 8), PALE, -1)  # "text"
        lines.append(OcrLine(text, 0.99, Region(x, y, 12 * len(text), H)))
    return image, lines


def channels_of(rows) -> list[str]:
    image, ocr = frame(rows)
    return [line.channel for line in channels.assign(parse(ocr), image, {})]


def test_same_colour_but_the_icon_tells_match_from_team():
    assert channels_of([("diamond", "[Pickle]: gg"), ("team", "[Void]: on my way")]) == [
        "match",
        "team",
    ]


def test_no_icon_falls_back_to_the_colour():
    assert channels_of([(None, "[Pickle]: gg")]) == ["unknown"]  # pale yellow matches no colour


def test_a_wrapped_line_keeps_the_icon_of_its_first_row():
    image, _ = frame([("team", "[Void]: this is a long line that"), (None, "wraps onto a second")])
    ocr = [OcrLine("[Void]: this is a long line that", 0.99, Region(100, 30, 400, H)),
           OcrLine("wraps onto a second", 0.99, Region(100, 70, 230, H))]  # fmt: skip
    (line,) = channels.assign(parse(ocr), image, {})
    assert line.channel == "team" and line.text.endswith("wraps onto a second")


def test_clear_icons_teach_the_colours():
    image, ocr = frame([("diamond", "[Pickle]: gg"), ("team", "[Void]: hi")])
    learned = channels.learn(parse(ocr), image)
    assert set(learned) == {"match", "team"}


def test_a_bright_background_hides_the_icon():
    image, ocr = frame([("diamond", "[Pickle]: gg")])
    image[:, :95] = PALE  # the background behind the icon is as bright as the text
    (line,) = parse(ocr)
    assert channels.icon_shape(image, line.head) is None


def draw(image, icon: str, cx: int, cy: int, colour, h: int = H) -> None:
    """The four chat icons at the sizes measured on real frames (#228), relative to the text."""
    if icon == "system":  # a full disc with a thin dark i in it
        cv2.circle(image, (cx, cy), int(0.26 * h), colour, -1)
        cv2.line(image, (cx, cy - 1), (cx, cy + 3), (12, 12, 12), 1)
    elif icon == "diamond":
        r = int(0.18 * h)
        cv2.fillPoly(image, [np.array([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)])],
                     colour)  # fmt: skip
    else:  # people: a head and a body each; team is three, wider than group's two
        for dx in {"team": (-11, 0, 11), "group": (-6, 6)}[icon]:
            cv2.circle(image, (cx + dx, cy - 6), 3, colour, -1)
            cv2.ellipse(image, (cx + dx, cy + 5), (4, 5), 0, 0, 360, colour, -1)


def channels_drawn(rows) -> list[str]:
    image = np.full((60 + len(rows) * 50, 900, 3), 12, np.uint8)
    ocr = []
    for i, (icon, text, colour, speck) in enumerate(rows):
        x, y = 100, 30 + i * 50
        cx, cy = int(x - 0.85 * H), y + H // 2
        draw(image, icon, cx, cy, colour)
        if speck:  # something bright in another colour right next to the icon
            cv2.rectangle(image, (cx - 22, cy - 10), (cx - 14, cy + 4), (255, 120, 40), -1)
        cv2.rectangle(image, (x, y + 8), (x + 12 * len(text), y + H - 8), colour, -1)
        ocr.append(OcrLine(text, 0.99, Region(x, y, 12 * len(text), H)))
    return [line.channel for line in channels.assign(parse(ocr), image, {})]


ORANGE, YELLOW, GREEN, MAGENTA = (40, 150, 255), (40, 220, 255), (120, 230, 60), (230, 60, 230)


def test_the_four_icons_by_shape_and_size():
    assert channels_drawn([
        ("team", "[Moon]: on my way", MAGENTA, False),
        ("group", "[Moon]: Test", GREEN, False),
        ("system", "[Pickle] was invited to the group.", YELLOW, False),
        ("diamond", "[Pickle]: gg wp", ORANGE, False),
    ]) == ["team", "group", "system", "match"]  # fmt: skip


def test_a_system_line_with_a_phrase_the_list_lacks_is_still_system(monkeypatch):
    """The round i icon (as measured on Void's crop, #228) makes "[Name] text" a system line,
    so a new system phrase doesn't need a code change. It's always yellow."""
    real_disc = channels.IconStats(blobs=1, width=0.47, height=0.5, fill=0.75, middle=0.66)
    monkeypatch.setattr(channels, "icon_stats", lambda *args: real_disc)
    image = np.full((120, 900, 3), 12, np.uint8)
    cv2.rectangle(image, (100, 38), (500, 30 + H - 8), YELLOW, -1)
    ocr = [OcrLine("[Pickle] was promoted to group leader.", 0.99, Region(100, 30, 400, H))]
    (line,) = channels.assign(parse(ocr), image, {})
    assert (line.kind, line.channel, line.speaker) == ("system", "system", "Pickle")
    assert line.text == "[Pickle] was promoted to group leader."
    cv2.rectangle(image, (100, 38), (500, 30 + H - 8), ORANGE, -1)  # not yellow: not system
    (line,) = channels.assign(parse(ocr), image, {})
    assert line.kind == "message"


def test_background_next_to_the_diamond_doesnt_make_it_people():
    assert channels_drawn([("diamond", "[Pickle]: gg", ORANGE, True)]) == ["match"]


CYAN, PALE_YELLOW, RIM = (255, 240, 60), (140, 245, 255), (40, 60, 90)  # BGR


def bright_frame(icon: str, background) -> tuple[np.ndarray, list[OcrLine]]:
    """A chat line on a bright HDR map (#403): the icon and the text as bright and as coloured
    as the background, only their dark rim and their colour set them apart."""
    image = np.zeros((120, 900, 3), np.uint8)
    image[:] = background
    x, y = 100, 40
    cx, cy = int(x - 1.05 * H), y + H // 2  # where it sits on real frames
    if icon == "diamond":
        r = int(0.2 * H)
        corners = np.array([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)])
        cv2.fillPoly(image, [corners], PALE_YELLOW)
        cv2.polylines(image, [corners], True, RIM, 2)
    else:
        for dx, size in ((-13, 0), (13, 0), (0, 2)):  # three people, the middle one in front
            cv2.circle(image, (cx + dx, cy - 6 - size), 4 + size, RIM, -1)
            cv2.circle(image, (cx + dx, cy - 6 - size), 3 + size, PALE_YELLOW, -1)
            cv2.ellipse(image, (cx + dx, cy + 5), (6 + size, 7 + size), 0, 0, 360, RIM, -1)
            cv2.ellipse(image, (cx + dx, cy + 5), (4 + size, 6 + size), 0, 0, 360, PALE_YELLOW, -1)
    for sx in range(x, x + 200, 12):  # thin letters: the box is mostly the map behind them
        cv2.line(image, (sx, y + 8), (sx, y + H - 8), PALE_YELLOW, 2)
    return image, [OcrLine("[Pickle]: hello everyone", 0.99, Region(x, y, 200, H))]


def test_the_icon_on_a_bright_map_is_found_by_how_it_stands_out():
    """#403: on a bright cyan map the old check saw one big blob; the icon's rim sets it apart."""
    for icon, channel in (("diamond", "match"), ("team", "team")):
        image, ocr = bright_frame(icon, CYAN)
        (line,) = parse(ocr)
        assert channels.icon_shape(image, line.head, channels.text_hue(image, line.box)) is None
        assert [c.channel for c in channels.assign(parse(ocr), image, {})] == [channel], icon


def test_a_busy_background_never_makes_a_wrong_channel():
    """A diamond on camouflage looked like a few blobs: on a bright background only the sure
    shapes count, so it's match or still unknown, never team or group."""
    rng = np.random.default_rng(3)
    for _ in range(20):
        image, ocr = bright_frame("diamond", CYAN)
        for _ in range(6):  # bright specks of the map around the icon
            px, py = int(rng.integers(40, 98)), int(rng.integers(30, 85))
            colour = tuple(int(c) for c in rng.integers(150, 256, 3))
            cv2.circle(image, (px, py), int(rng.integers(2, 5)), colour, -1)
        (line,) = channels.assign(parse(ocr), image, {})
        assert line.channel in ("match", "unknown")


def test_classify_on_background_keeps_only_the_sure_shapes():
    real = {  # measured on Marv's bright 4K HDR frames, checked by eye (#403)
        "diamond": channels.IconStats(1, 0.42, 0.42, 0.55, 0.9),
        "three people": channels.IconStats(6, 0.92, 0.64, 0.38, 0.78),
        "diamond on camouflage": channels.IconStats(5, 0.93, 0.71, 0.22, 0.06),
        "two people": channels.IconStats(4, 0.59, 0.76, 0.42, 0.59),
    }
    got = {name: channels.classify_on_background(stats) for name, stats in real.items()}
    assert got == {"diamond": "match", "three people": "team", "diamond on camouflage": None,
                   "two people": None}  # fmt: skip

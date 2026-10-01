"""Hero select starts a match (#93): synthetic strips and a fake OCR, real logic."""

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from yaptracker.capture.source import Region
from yaptracker.signals import HeroSelect, has_bright_text, parse_info, signal_regions


def strip(text: str | None) -> np.ndarray:
    img = Image.new("RGB", (780, 60), (40, 44, 52))
    if text:
        ImageDraw.Draw(img).text((20, 10), text, fill=(240, 240, 240),
                                 font=ImageFont.load_default(size=34))  # fmt: skip
    return np.ascontiguousarray(np.asarray(img)[:, :, ::-1])


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def detector(screens, clock):
    """screens: what the fake OCR 'reads' for each strip, keyed by id(strip)."""
    starts = []

    def read_lines(image):
        return screens.get(id(image), [])

    def read_line(image):
        return " ".join(read_lines(image))

    def on_start(mode, map_name):
        starts.append((mode, map_name))

    return HeroSelect(read_line, read_lines, on_start, clock), starts


def test_regions_scale_with_the_window():
    assert signal_regions(2560, 1440)["heroselect"] == Region(60, 330, 780, 60)
    assert signal_regions(1920, 1080)["heroselect"] == Region(45, 248, 585, 45)


def test_bright_text_check_skips_empty_strips():
    assert has_bright_text(strip("ASSEMBLE YOUR TEAM"))
    assert not has_bright_text(strip(None))


def test_mode_and_map_come_from_the_corner():
    assert parse_info(["UNRANKED", "ATTACK", "ESPERANÇA"]) == ("UNRANKED", "ESPERANÇA")
    # Real OCR reads (#93): side glued to the mode, a letter wrong, no cedilla.
    assert parse_info(["UINRANKED ATTACK", "ESPERANCA"]) == ("UNRANKED", "ESPERANCA")
    assert parse_info(["LINRANKED DEFEND", "EICHENWALDE"]) == ("UNRANKED", "EICHENWALDE")
    assert parse_info(["MYSTERY HEROES", "KINGS ROW"]) == ("MYSTERY HEROES", "KINGS ROW")
    assert parse_info([]) == (None, None)


def test_single_letters_never_count_as_the_banner():
    # In-game noise the strip really read (#93) - partial matching would call these 100 %.
    from yaptracker.signals import is_banner

    assert not any(is_banner(t) for t in ["m", "O", "AM", "Y", "FE", "ECCODT", "MARTINS"])
    assert is_banner("ASSEMBLE YOUR TEAM") and is_banner("ASSEMBLEYOUR TEAN")


def test_one_hero_select_starts_exactly_one_match_with_mode_and_map():
    clock = Clock()
    banner, info = strip("ASSEMBLE YOUR TEAM"), strip("UNRANKED")
    hs, starts = detector({id(banner): ["ASSEMBLE YOUR TEAM"],
                           id(info): ["UNRANKED", "ATTACK", "ESPERANÇA"]}, clock)  # fmt: skip
    for t in range(30):  # 30 s of hero select, read once a second
        clock.now = t
        hs.update({"heroselect": banner, "heroselect_info": info})
    assert starts == [("UNRANKED", "ESPERANÇA")]


def test_ocr_slips_still_count_and_other_text_does_not():
    clock = Clock()
    slip, other = strip("ASSEMBLE YOUR TEAM"), strip("PLAY OF THE GAME")
    hs, starts = detector({id(slip): ["ASSEMBLEYOUR TEAN"], id(other): ["PLAY OF THE GAME"]}, clock)
    hs.update({"heroselect": other})
    assert starts == []
    hs.update({"heroselect": slip})
    assert len(starts) == 1


def test_the_next_hero_select_counts_once_the_banner_was_gone_long_enough():
    clock = Clock()
    banner, empty = strip("ASSEMBLE YOUR TEAM"), strip(None)
    hs, starts = detector({id(banner): ["ASSEMBLE YOUR TEAM"]}, clock)
    hs.update({"heroselect": banner})
    for t in range(1, 60):  # a short gap (e.g. a few unreadable frames) doesn't re-arm
        clock.now = t
        hs.update({"heroselect": empty})
    clock.now = 61
    hs.update({"heroselect": banner})
    assert len(starts) == 1
    for t in range(62, 62 + 600):  # the match itself: 10 minutes without the banner
        clock.now = t
        hs.update({"heroselect": empty})
    hs.update({"heroselect": banner})
    assert len(starts) == 2


def test_round_start_box_starts_a_match_only_if_none_is_running():
    from yaptracker.signals import is_round_start

    assert is_round_start("PREPARE YOUR DEFENSES 0:44") and is_round_start("PREPARE TO ATTACK")
    assert not is_round_start("P") and not is_round_start("REPAIR")
    clock, empty, box = Clock(), strip(None), strip("PREPARE TO ATTACK")
    running = {"match": True}
    starts = []

    def on_start(mode, map_name):
        starts.append((mode, map_name))

    reads = {id(box): "PREPARE TO ATTACK 0:30"}
    hs = HeroSelect(lambda img: reads.get(id(img), ""), lambda img: [], on_start, clock,
                    match_running=lambda: running["match"])  # fmt: skip
    hs.update({"heroselect": empty, "round_start": box})  # a later round of a running match
    assert starts == []
    running["match"] = False  # YapTracker started late: no match yet
    hs.update({"heroselect": empty, "round_start": box})
    assert starts == [(None, None)]


def test_real_recording_of_two_matches_gives_exactly_two_starts(monkeypatch):
    """Replay of what the detector saw in a real OBS recording, once a second (#93).

    tests/fixtures/signals/two-matches.json: per second the single-line read of each strip, or
    null where the cheap pixel check said "no text" (then nothing is read). Non-signal text is
    scrambled; only the banner, round-start box, modes and maps are kept.
    """
    import json
    from pathlib import Path

    import yaptracker.signals as signals

    path = Path(__file__).parent / "fixtures" / "signals" / "two-matches.json"
    ticks = json.loads(path.read_text(encoding="utf-8"))["ticks"]
    texts: dict[int, str | None] = {}
    lines: dict[int, list[str]] = {}
    monkeypatch.setattr(signals, "has_bright_text", lambda img, **_: texts[id(img)] is not None)
    clock, starts, running = Clock(), [], {"match": False}

    def on_start(mode, map_name):
        starts.append((clock.now, mode, map_name))
        running["match"] = True

    hs = HeroSelect(lambda img: texts[id(img)], lambda img: lines.get(id(img), []), on_start, clock,
                    match_running=lambda: running["match"])  # fmt: skip
    for tick in ticks:
        clock.now = tick["t"]
        crops = {name: np.zeros((2, 2, 3), np.uint8) for name in ("heroselect", "round_start",
                                                                   "heroselect_info")}  # fmt: skip
        for name in ("heroselect", "round_start"):
            texts[id(crops[name])] = tick[name]
        lines[id(crops["heroselect_info"])] = tick.get("heroselect_info", [])
        hs.update(crops)
    assert starts == [(88.0, "UNRANKED", "ESPERANCA"), (769.0, "UNRANKED", "EICHENWALDE")]

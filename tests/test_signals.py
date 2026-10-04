"""Hero select starts a match (#93), the end screen ends it (#94): synthetic strips and a fake
OCR, real logic."""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from yaptracker import signals
from yaptracker.capture.source import Region
from yaptracker.signals import (
    EndScreen,
    HeroSelect,
    banner_outcome,
    has_bright_text,
    has_colour,
    is_banner,
    parse_info,
    signal_regions,
    title_end,
)

RECORDING = Path(__file__).parent / "fixtures" / "signals" / "two-matches.json"


def strip(text: str | None) -> np.ndarray:
    img = Image.new("RGB", (780, 60), (40, 44, 52))
    if text:
        ImageDraw.Draw(img).text((20, 10), text, fill=(240, 240, 240),
                                 font=ImageFont.load_default(size=34))  # fmt: skip
    return np.ascontiguousarray(np.asarray(img)[:, :, ::-1])


def banner(text: str, colour: tuple[int, int, int]) -> np.ndarray:
    """The big centre banner: huge letters in the friendly or enemy colour."""
    img = Image.new("RGB", (820, 250), (40, 44, 52))
    ImageDraw.Draw(img).text((20, 0), text, fill=colour, font=ImageFont.load_default(size=200))
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
    assert parse_info(["UNRANKED", "ATTACK", "ESPERANÇA"]) == ("UNRANKED", "Esperança")
    # Real OCR reads (#93): side glued to the mode, a letter wrong, no cedilla. Maps come back
    # as the game lists spell them (#276).
    assert parse_info(["UINRANKED ATTACK", "ESPERANCA"]) == ("UNRANKED", "Esperança")
    assert parse_info(["LINRANKED DEFEND", "EICHENWALDE"]) == ("UNRANKED", "Eichenwalde")
    assert parse_info(["MYSTERY HEROES", "KINGS ROW"]) == ("MYSTERY HEROES", "King's Row")
    assert parse_info([]) == (None, None)


def test_garbage_modes_and_maps_are_none_not_stored_as_read():
    """#252's log: "UINRH" (Route 66), "INRONKED ALU9CK", "NEPAL NE", "66", a sub-map."""
    assert parse_info(["UINRH", "ROUTE 66"]) == (None, "Route 66")
    assert parse_info(["INRONKED ALU9CK", "66"]) == (None, None)
    assert parse_info(["UNRANKED ATTACK", "NEPAL NE"]) == ("UNRANKED", "Nepal")
    assert parse_info(["COMPETITIVE", "LIJIANGTOWER·NIGHT MARKET"]) == (
        "COMPETITIVE",
        "Lijiang Tower",
    )
    assert parse_info(["SCHNELLES SPIEL ANGRIFF", "PARAISO"]) == ("SCHNELLES SPIEL", "Paraíso")


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
    assert starts == [("UNRANKED", "Esperança")]


def test_ocr_slips_still_count_and_other_text_does_not():
    clock = Clock()
    slip, other = strip("ASSEMBLE YOUR TEAM"), strip("PLAY OF THE GAME")
    hs, starts = detector({id(slip): ["ASSEMBLEYOUR TEAN"], id(other): ["PLAY OF THE GAME"]}, clock)
    hs.update({"heroselect": other})
    assert starts == []
    clock.now += signals.BETWEEN_EVERY_S  # the next look (#303); the banner is up for 20 s+
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
    import yaptracker.signals as signals

    ticks = json.loads(RECORDING.read_text(encoding="utf-8"))["ticks"]
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
    assert starts == [(88.0, "UNRANKED", "Esperança"), (769.0, "UNRANKED", "Eichenwalde")]


def test_end_crops_scale_with_the_window():
    assert signal_regions(2560, 1440)["end_banner"] == Region(900, 590, 820, 250)
    assert signal_regions(1920, 1080)["end_title"] == Region(30, 22, 675, 56)


def test_the_banner_check_wants_big_coloured_letters():
    assert has_colour(banner("DEFEAT", (230, 60, 50)))
    assert has_colour(banner("VICTORY!", (150, 230, 60)))
    assert not has_colour(banner("DEFEAT", (200, 200, 200)))  # grey in-game text
    assert not has_colour(strip("DEFEAT"))  # small letters


@pytest.mark.parametrize(
    ("text", "outcome"),
    [("VICTORY!", "victory"), ("VICTORYI", "victory"), ('DEFEAT"', "defeat"),
     ("DRAW", "draw"), ("ViR", None), ("VIY", None), ("CNOTR", None), ("TDEEEOTT", None),
     ("DRA", None), ("", None)],
)  # fmt: skip
def test_banner_reads(text, outcome):  # real reads and real noise from the recording (#94)
    assert banner_outcome(text) == outcome


@pytest.mark.parametrize(
    ("text", "result"),
    [("PLAY OF THE GAME MAUGA", (True, None)), ("PLAY OFTHEGAME MOIRA", (True, None)),
     ("VICTORY ESPERANCA", (True, "victory")), ("DEFEATECHENWALDEE", (True, "defeat")),
     ("UMMARYREWARS", (True, None)), ("UNRANKED ATTACK", (False, None)),
     ("VICTORY", (False, None)), ("SA ACK", (False, None))],
)  # fmt: skip
def test_title_reads(text, result):
    assert title_end(text) == result


def end_screen(reads, clock):
    ends = []
    return EndScreen(lambda img: reads.get(id(img), ""), ends.append, clock), ends


def test_one_banner_ends_the_match_once_with_its_outcome():
    clock = Clock()
    victory = banner("VICTORY!", (150, 230, 60))
    potg, quiet = strip("PLAY OF THE GAME"), strip(None)
    es, ends = end_screen({id(victory): "VICTORY!", id(potg): "PLAY OF THE GAME MAUGA"}, clock)
    for t in range(4):  # the banner stays ~4 s
        clock.now = t
        es.update({"end_banner": victory, "end_title": quiet})
    for t in range(4, 30):  # then PLAY OF THE GAME
        clock.now = t
        es.update({"end_banner": quiet, "end_title": potg})
    assert ends == ["victory"]


def test_play_of_the_game_ends_it_when_the_banner_was_missed_and_the_outcome_follows():
    clock = Clock()
    potg, summary, quiet = strip("PLAY OF THE GAME"), strip("DEFEAT EICHENWALDE"), strip(None)
    reads = {id(potg): "PLAY OF THE GAME MOIRA", id(summary): "DEFEATECHENWALDEE"}
    es, ends = end_screen(reads, clock)
    for t, title in [(0, potg), (3, potg), (6, summary), (9, summary)]:
        clock.now = t
        es.update({"end_banner": quiet, "end_title": title})
    assert ends == [None, "defeat"]


def test_the_next_end_counts_once_the_end_screens_were_gone_long_enough():
    clock = Clock()
    defeat, quiet = banner("DEFEAT", (230, 60, 50)), strip(None)
    es, ends = end_screen({id(defeat): "DEFEAT"}, clock)
    es.update({"end_banner": defeat})
    for t in range(1, 600):  # the next match
        clock.now = t
        es.update({"end_banner": quiet, "end_title": quiet})
    es.update({"end_banner": defeat})
    assert ends == ["defeat", "defeat"]


def test_real_recording_of_two_matches_gives_two_matches_with_outcomes(monkeypatch, tmp_path):
    """The whole evening path: hero select starts, end screen ends, real MatchTracker and store.

    Same recording as above; per second the read of each crop, or null where the cheap check
    said "nothing here" (then nothing is read).
    """
    import yaptracker.signals as signals
    from yaptracker.matches import MatchTracker
    from yaptracker.pause import Pause
    from yaptracker.store.repo import Store

    ticks = json.loads(RECORDING.read_text(encoding="utf-8"))["ticks"]
    names = ("heroselect", "heroselect_info", "round_start", "end_banner", "end_title")
    texts: dict[int, str | None] = {}
    lines: dict[int, list[str]] = {}
    present = lambda img, **_: texts[id(img)] is not None  # noqa: E731
    monkeypatch.setattr(signals, "has_bright_text", present)
    monkeypatch.setattr(signals, "has_colour", present)
    clock, t0 = Clock(), 1_000_000.0
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    tracker = MatchTracker(store, Pause(), clock=lambda: t0 + clock.now)
    hs = HeroSelect(lambda img: texts[id(img)], lambda img: lines.get(id(img), []),
                    lambda mode, map_name: tracker.new_match(source="heroselect", mode=mode,
                                                             map_name=map_name),
                    clock, match_running=lambda: tracker.running)  # fmt: skip
    es = EndScreen(lambda img: texts[id(img)], lambda outcome: tracker.end_match(outcome=outcome),
                   clock)  # fmt: skip
    for tick in ticks:
        clock.now = tick["t"]
        tracker.capture_alive()
        crops = {name: np.zeros((2, 2, 3), np.uint8) for name in names}
        for name in names:
            texts[id(crops[name])] = tick.get(name) if name != "heroselect_info" else ""
        lines[id(crops["heroselect_info"])] = tick.get("heroselect_info", [])
        hs.update(crops)
        es.update(crops)
    rows = store._read("SELECT started_at, ended_at, outcome, source, map FROM matches ORDER BY id")
    store.close()
    assert [(s - t0, e - t0, o, src, m) for s, e, o, src, m in rows] == [
        (88.0, 657.0, "victory", "heroselect", "Esperança"),
        (769.0, 1348.0, "defeat", "heroselect", "Eichenwalde"),
    ]


FOUR_K = json.loads((Path(__file__).parent / "fixtures" / "signals" / "4k-hdr.json").read_text(
    encoding="utf-8"))  # fmt: skip


def washed(text: str) -> np.ndarray:
    """A 4K hero-select strip with HDR on (#170): white letters with a faint shadow on a ground
    Windows washed out to near-white."""
    img = Image.new("RGB", (1170, 90), (232, 230, 226))
    if text:
        ImageDraw.Draw(img).text((30, 15), text, fill=(255, 255, 255), stroke_width=2,
                                 stroke_fill=(160, 160, 160),
                                 font=ImageFont.load_default(size=52))  # fmt: skip
    return np.ascontiguousarray(np.asarray(img)[:, :, ::-1])


def test_4k_strips_pass_the_pixel_check_like_1440p_ones():
    import cv2

    at_4k = cv2.resize(strip("ASSEMBLE YOUR TEAM"), None, fx=1.5, fy=1.5)
    assert has_bright_text(at_4k)
    assert not has_bright_text(cv2.resize(strip(None), None, fx=1.5, fy=1.5))


def test_a_washed_out_hdr_banner_still_passes_the_pixel_check():
    assert has_bright_text(washed("ASSEMBLE YOUR TEAM"))
    assert not has_bright_text(washed(""))  # just the washed-out ground


def test_4k_hdr_readings_from_a_real_evening():
    assert all(is_banner(s["banner"]) for s in FOUR_K["starts"])
    assert [parse_info(s["info"]) for s in FOUR_K["starts"]] == [
        (None, "New Queen Street"),  # "O ATTACK": the queue name was washed out, no guess
        ("UNRANKED", "Route 66"),
        ("UNRANKED", "Hollywood"),
        ("UNRANKED", "Esperança"),
        ("UNRANKED", "Junkertown"),
    ]
    assert [banner_outcome(e["banner"]) for e in FOUR_K["ends"]] == [
        "defeat", "victory", "defeat", "victory", "victory", "victory", "defeat", "victory",
    ]  # fmt: skip
    assert parse_info(["STADIUM ATTACK", "COLOSSEO"]) == ("STADIUM", "Colosseo")


def test_a_match_without_hero_select_saves_a_look_back():
    from yaptracker.matches import MatchTracker
    from yaptracker.pause import Pause
    from yaptracker.store.repo import Store

    store = Store.open(Path(":memory:"), Path("/nonexistent"))
    missed = []
    tracker = MatchTracker(store, Pause(), on_missed_start=missed.append)
    tracker.new_match(100.0, source="heroselect")
    tracker.chat_changed(130.0)
    tracker.end_match(700.0, "victory")
    tracker.chat_changed(900.0)  # next match by chat after the end: hero select was missed
    tracker.new_match(1500.0)  # the New match button
    assert missed == ["gap", "hotkey"]  # chat after a result: hero select missed (#275)
    store.close()


def test_hero_select_is_looked_for_every_few_seconds_not_every_frame():
    """#303: the gate passes on most frames, each look an OCR read; the screen is up 20 s+."""
    clock, reads = Clock(), []
    banner = strip("ASSEMBLE YOUR TEAM")
    running = {"on": False}

    def read(img):
        reads.append(clock.now)
        return "ASSEMBLE YOUR TEAM" if img is banner else "TEAM 1 OBJECTIVE"

    hud = strip("TEAM 1 OBJECTIVE")
    starts = []
    hs = signals.HeroSelect(read, lambda img: [], lambda *a: starts.append(clock.now), clock,
                            match_running=lambda: running["on"])  # fmt: skip
    for t in range(10):  # between matches: menus with bright text
        clock.now = t
        hs.update({"heroselect": hud})
    assert reads == [0, 2, 4, 6, 8]
    running["on"], reads[:] = True, []
    for t in range(10, 30):  # in a match: the HUD keeps the gate open
        clock.now = t
        hs.update({"heroselect": hud})
    assert reads == [13, 18, 23, 28]  # 5 s after the last look (8)
    for t in range(30, 60):  # the end screen was missed; the next hero select still counts
        clock.now = t
        hs.update({"heroselect": banner})
    assert starts and starts[0] <= 35

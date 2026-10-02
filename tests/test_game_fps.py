"""The game's FPS from Overwatch's performance overlay (#212): drawn overlay rows, the real OCR."""

import logging

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from yaptracker.game_fps import READ_EVERY_S, FpsMeter, fps_box, overlay_regions, parse_fps
from yaptracker.ocr import engine as ocr

SDR = {"box": (31, 34, 56), "ink": (170, 173, 192)}  # RGB, measured at 1440p
HDR = {"box": (42, 52, 80), "ink": (245, 255, 255)}  # the 4K HDR evening of 2026-10-01


def top_right(height: int, fps: int | None, ground=(150, 120, 100), colours=SDR) -> np.ndarray:
    """The top edge of a game screen, with the overlay row as Overwatch draws it (1440p sizes)."""
    s, width = height / 1440, height * 16 // 9
    img = Image.new("RGB", (width, round(40 * s)), ground)
    draw, font = ImageDraw.Draw(img), ImageFont.load_default(size=round(15 * s))
    right = width - round(3 * s)
    if fps is not None:
        for text, box_w in [("LATENCY: 39 MS", 141), ("VRAM: 5304 MB", 125), (f"FPS: {fps}", 82)]:
            left = right - round(box_w * s)
            draw.rectangle([left, round(2 * s), right - 1, round(24 * s) - 1], fill=colours["box"])
            draw.text((left + round(13 * s), round(6 * s)), text, fill=colours["ink"], font=font)
            right = left - round(3 * s)
    return np.ascontiguousarray(np.asarray(img)[:, :, ::-1])


def strip(screen: np.ndarray, height: int) -> np.ndarray:
    return overlay_regions(height * 16 // 9, height)["fps"].crop(screen)


def read(screen: np.ndarray, height: int) -> int | None:
    box = fps_box(strip(screen, height), height)
    return None if box is None else parse_fps(ocr.get("rapidocr").read_line(box))


@pytest.mark.parametrize("height", [1440, 2160])
def test_reads_the_fps_box_at_1440p_and_4k(height):
    assert read(top_right(height, 181), height) == 181
    assert read(top_right(height, 59), height) == 59


def test_a_dark_ground_hides_the_gaps_between_the_boxes_and_it_still_reads():
    assert read(top_right(1440, 142, ground=(38, 40, 52)), 1440) == 142


def test_hdr_colours():
    assert read(top_right(2160, 97, ground=(20, 20, 24), colours=HDR), 2160) == 97


@pytest.mark.parametrize("ground", [(150, 120, 100), (12, 14, 18), (31, 34, 56), (240, 240, 250)])
def test_no_overlay_no_box(ground):
    assert fps_box(strip(top_right(1440, None, ground=ground), 1440), 1440) is None


@pytest.mark.parametrize(("text", "fps"), [("FPS:181", 181), ("FPS: 59", 59), ("FPS", None),
                                           ("V", None), ("", None), ("CY:40MS", None)])  # fmt: skip
def test_real_reads(text, fps):  # what RapidOCR made of real boxes (and of wrong crops)
    assert parse_fps(text) == fps


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def meter(clock, values, state):
    reads = iter(values)
    calls = []

    def read_line(box):
        calls.append(box.shape)
        return f"FPS:{next(reads)}"

    return FpsMeter(read_line, lambda: state["now"], clock), calls


def test_one_log_line_a_minute_with_median_p10_and_the_state(caplog):
    clock, state = Clock(), {"now": "running"}
    minute = [150, 160, 170, 90, 165, 155, 175, 160, 150, 145, 170, 165]
    fps, calls = meter(clock, [*minute, 99], state)
    signals = {"fps": strip(top_right(1440, 160), 1440)}
    with caplog.at_level(logging.INFO, logger="yaptracker.game_fps"):
        for _ in range(65):  # once a second, like the capture's crops
            fps.update(signals, 1440)
            clock.now += 1
    assert len(calls) == 13  # every 5 s, not every second
    (line,) = [r.getMessage() for r in caplog.records]
    assert line.startswith("game fps (Overwatch overlay): median 160, p10 146, n=12 — running;")


def test_a_pause_closes_the_minute_so_each_line_is_one_state(caplog):
    clock, state = Clock(), {"now": "running"}
    fps, _ = meter(clock, [150] * 4 + [200] * 5, state)
    signals = {"fps": strip(top_right(1440, 150), 1440)}
    with caplog.at_level(logging.INFO, logger="yaptracker.game_fps"):
        for t in range(40):
            state["now"] = "paused" if t >= 20 else "running"
            fps.update(signals, 1440)
            clock.now += 1
        clock.now += 60
        fps.update(signals, 1440)
    lines = [r.getMessage() for r in caplog.records]
    assert [line.split(" — ")[1].split(";")[0] for line in lines] == ["running", "paused"]
    assert "median 150, p10 150, n=4" in lines[0] and "median 200" in lines[1]


def test_overlay_off_reads_nothing_and_logs_nothing(caplog):
    clock, state = Clock(), {"now": "gpu-ocr"}
    fps, calls = meter(clock, [], state)
    with caplog.at_level(logging.INFO, logger="yaptracker.game_fps"):
        for _ in range(130):
            fps.update({"fps": strip(top_right(1440, None), 1440)}, 1440)
            fps.update({}, 1440)  # a tick without the strip
            clock.now += 1
    assert calls == [] and caplog.records == []
    assert READ_EVERY_S == 5.0

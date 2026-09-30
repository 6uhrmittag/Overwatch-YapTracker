"""Parser on anonymised OCR output of real screenshots (tests/fixtures/chat, names are fake)."""

import json
from pathlib import Path

import pytest

from yaptracker.capture.source import Region
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import ChatLine, parse

FIXTURES = sorted((Path(__file__).parent / "fixtures" / "chat").glob("*.json"))


def as_dict(line: ChatLine) -> dict:
    d = {"kind": line.kind, "channel": line.channel, "text": line.text}
    d.update({k: v for k in ("speaker", "hero", "target") if (v := getattr(line, k))})
    if line.flagged:
        d["flagged"] = True
    return d


def ocr_lines(fixture: dict) -> list[OcrLine]:
    return [OcrLine(o["text"], o["confidence"], Region(*o["box"])) for o in fixture["ocr"]]


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_real_screenshots_parse_as_expected(path):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    assert [as_dict(line) for line in parse(ocr_lines(fixture))] == fixture["expected"]


def _line(text, y, confidence=0.99, x=64, h=24):
    return OcrLine(text, confidence, Region(x, y, 400, h))


def test_every_ocr_line_lands_somewhere():
    lines = [_line("GAL", 10), _line("[A]: hi", 50), _line("LEVEL35", 90)]
    assert [p.kind for p in parse(lines)] == ["unknown", "message", "unknown"]


def test_wrapped_line_is_joined_but_a_new_message_is_not():
    lines = [_line("[A]: this is long", 10), _line("and wraps", 39), _line("next line", 80)]
    parsed = parse(lines)
    assert [p.text for p in parsed] == ["this is long and wraps", "next line"]
    assert parsed[0].box == Region(64, 10, 400, 53)


def test_comms_wheel_lines_are_team_with_hero_and_target():
    (line,) = parse([_line("Ana (Ana) to Bo (Reinhardt): Thanks!", 10)])
    assert (line.channel, line.speaker, line.hero, line.target, line.text) == (
        "team", "Ana", "Ana", "Bo", "Thanks!",
    )  # fmt: skip


def test_missing_space_after_colon_and_fullwidth_colon():
    assert [p.text for p in parse([_line("[A]:Heyy", 10), _line("[B]：hi", 50)])] == ["Heyy", "hi"]


def test_report_link_is_stripped_and_flagged():
    (line,) = parse([_line("[A]: rude [Report]", 10)])
    assert (line.text, line.flagged) == ("rude", True)


def test_input_line_of_the_open_chat_is_marked():
    (line,) = parse([_line("[Team] PRESS TAB TO CYCLE CHANNELS", 10)])
    assert line.kind == "input"


def test_a_player_called_match_is_still_a_message():
    (line,) = parse([_line("[Match]: hi", 10)])
    assert (line.kind, line.speaker) == ("message", "Match")


def test_comms_line_with_nothing_after_the_colon_is_kept_not_a_crash():
    # Real shape (#88): the message text sat on the next visual line and wasn't joined.
    (line,) = parse([_line("Ana (Ana) to Bo (Zarya):", 10)])
    assert (line.kind, line.speaker, line.target, line.text) == ("comms", "Ana", "Bo", "")

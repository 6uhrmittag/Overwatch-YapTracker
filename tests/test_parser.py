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


def test_friends_online_is_a_system_line_without_a_name():
    lines = [_line("1 friend playing Overwatch.", 10), _line("12 friends playing Overwatch.", 50),
             _line("[1friend]: playing Overwatch.", 90)]  # fmt: skip
    assert [(p.kind, p.channel, p.speaker) for p in parse(lines)] == [
        ("system", "system", None),
        ("system", "system", None),
        ("message", "unknown", "1friend"),
    ]


def test_a_lost_colon_is_chat_not_a_system_line():
    """#184: "[Name] WW" was taken as a system line; only a few phrases really are."""
    from yaptracker.parser import _classify

    for said in ("WW", "fun game :3", "luv u"):
        line = _classify(f"[Pickle] {said}", 0.9, Region(0, 0, 10, 10))
        assert (line.kind, line.speaker, line.text) == ("message", "Pickle", said)
    for system in ("started playing Overwatch.", "joined the game.", "left the game.",
                   "invited you to a group!"):  # fmt: skip
        assert _classify(f"[Pickle] {system}", 0.9, Region(0, 0, 10, 10)).kind == "system"
    assert _classify("[Pickle]: : WW", 0.9, Region(0, 0, 10, 10)).text == "WW"
    assert _classify("[Pickle]: :3", 0.9, Region(0, 0, 10, 10)).text == ":3"  # an emoticon


def test_real_readings_of_one_line_are_stored_once():
    """#184 replay: "[Me]: : WW", "[Me] WW" and "[Me]: ww" across frames are one line."""
    import json

    from yaptracker.dedup import Dedup
    from yaptracker.identity import Identity

    fixture = json.loads((Path(__file__).parent / "fixtures" / "dedup" /
                          "184-two-readings.json").read_text(encoding="utf-8"))  # fmt: skip
    me = Identity(me=("tortillaTank#1234",))
    for name, frames in fixture["sequences"].items():
        dedup, stored = Dedup(), []
        for frame in frames:
            ocr = [OcrLine(o["text"], o["confidence"], Region(*o["box"])) for o in frame["ocr"]]
            new, _ = dedup.update(frame["t"], me.apply(parse(ocr)))
            stored += [y.best for y in new]
        mine = [(y.kind, y.text.lower()) for y in stored if y.speaker == "tortillaTank"]
        assert all(kind != "system" for kind, _ in mine), name
        if name == "ww":
            assert [t for _, t in mine].count("ww") == 1
        else:
            assert any(t.startswith("fun game :3") for _, t in mine)  # chat, not system

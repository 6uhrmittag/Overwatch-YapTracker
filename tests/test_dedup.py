"""Each chat line once (#18): real frames replayed, plus the cases behind each rule."""

import json
from pathlib import Path

from yaptracker.capture.source import Region
from yaptracker.dedup import Dedup
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import ChatLine, parse

REPLAY = Path(__file__).parent / "fixtures" / "dedup" / "esperanca-match-end.json"


def yap(text, speaker="NoodleBonk", confidence=0.99, kind="message", role=None):
    return ChatLine(kind, "match", text, confidence, Region(0, 0, 100, 20), speaker=speaker,
                    role=role)  # fmt: skip


def texts(yaps):
    return [y.best.text for y in yaps]


def test_four_real_minutes_of_chat_give_each_line_once():
    """116 frames the change detector passed (the end of a match): lines scroll, fade, come back
    when the chat opens, get misread and get background text glued on."""
    frames = json.loads(REPLAY.read_text(encoding="utf-8"))["frames"]
    dedup, stored = Dedup(), []
    for frame in frames:
        ocr = [OcrLine(o["text"], o["confidence"], Region(*o["box"])) for o in frame["ocr"]]
        new, _ = dedup.update(frame["t"], parse(ocr))
        stored += new
    assert [(y.best.kind, y.best.speaker, y.best.text) for y in stored] == [
        ("comms", "NoodleBonk", "Hello!"),
        ("comms", "tortillaTank", "Thanks! ◇"),  # its icon (#259)
        ("comms", "MaybeMaybe", "Enemy Tracer!"),
        ("message", "tortillaTank", "tracer come heereee I have cookies"),
        ("comms", "zappy", "wants to stop the robot!"),
        ("message", "mossyfox", "gg"),
        ("message", "zappy", "gg"),
        ("message", "MaybeMaybe", "gg"),
        ("message", "SirPeelsALot", "gg"),
        ("message", "NoodleBonk", "gg wp"),
        ("message", "tortillaTank", "eehehe :3"),  # also read as "eehehe /3" and "eehehe"
        ("message", "tortillaTank", "gg"),
        ("system", None, "You endorsed NoodleBonk!"),
        ("system", None, "You endorsed MaybeMaybe!"),
    ]
    assert (stored[0].best.hero, stored[0].best.target) == ("Sierra", "you")


def test_a_line_scrolling_up_is_the_same_line():
    dedup = Dedup()
    assert texts(dedup.update(0.0, [yap("hi")])[0]) == ["hi"]
    assert texts(dedup.update(1.0, [yap("hi"), yap("o/")])[0]) == ["o/"]
    assert texts(dedup.update(2.0, [yap("hi"), yap("o/"), yap("hi")])[0]) == ["hi"]  # said twice


def test_a_misread_name_or_a_missing_line_is_still_the_same_chat():
    dedup = Dedup()
    dedup.update(0.0, [yap("hi"), yap("o/", "tortillaTank"), yap("gg", "zappy")])
    new, _ = dedup.update(1.0, [yap("hi", "NoodIeBonk"), yap("gg", "zappy")])
    assert new == []


def test_gg_again_after_the_first_one_faded_counts_again():
    dedup = Dedup()
    dedup.update(0.0, [yap("gg")])
    assert dedup.update(5.0, [yap("gg")])[0] == []  # still on screen
    assert texts(dedup.update(30.0, [yap("gg")])[0]) == ["gg"]  # a new one


def test_opening_the_chat_shows_old_lines_again_but_only_the_bottom_one_is_new():
    dedup = Dedup()
    dedup.update(0.0, [yap("hi"), yap("o/", "tortillaTank")])
    reopened = [yap("from before YapTracker", "zappy"), yap("hi"), yap("o/", "tortillaTank"),
                yap("new!", "zappy")]  # fmt: skip
    assert texts(dedup.update(60.0, reopened)[0]) == ["new!"]


def test_the_reading_seen_most_often_wins_over_one_confident_glitch():
    dedup = Dedup()
    (first,), _ = dedup.update(0.0, [yap("Oops XD", confidence=0.95)])
    _, improved = dedup.update(0.5, [yap("Oops XD EM PORTUGAL", confidence=0.99)])
    assert improved == [first] and first.best.text == "Oops XD EM PORTUGAL"  # 1:1, more confident
    for t in (1.0, 1.5):
        dedup.update(t, [yap("Oops XD", confidence=0.96)])
    assert first.best.text == "Oops XD"


def test_only_a_changed_reading_counts_as_improved():
    dedup = Dedup()
    dedup.update(0.0, [yap("hi", confidence=0.9)])
    assert dedup.update(1.0, [yap("hi", confidence=0.99)]) == ([], [])


def test_the_role_from_me_and_my_crew_stays_with_the_line():
    dedup = Dedup()
    (mine,), _ = dedup.update(0.0, [yap("hi", "tortillaTank", role="me")])
    assert mine.best.role == "me"


def test_input_line_and_unreadable_lines_never_become_yaps():
    dedup = Dedup()
    lines = [yap("Iiuiiuiliu", None, kind="cut"), yap("PORTUGAL", None, kind="unknown"),
             yap("[Match] eehehe", None, kind="input")]  # fmt: skip
    assert dedup.update(0.0, lines) == ([], [])


def test_glued_background_capitals_are_ignored_for_matching_only():
    from yaptracker.dedup import match_key

    assert match_key(yap("gg TOURING EM PORTU", "mossyfox")) == "mossyfox gg"  # real reads (#18)
    assert match_key(yap("Enemy Tracer! MAGIN", "MaybeMaybe")) == "maybemaybe enemy tracer"
    assert match_key(yap("GG WP")) == "noodlebonk gg wp"  # all caps on purpose: kept


def test_readings_that_differ_in_case_or_punctuation_are_one_line():
    """#184: "[Name]: : WW" and "[Name]: ww" were stored as two lines."""
    from yaptracker.dedup import match_key

    assert match_key(yap("WW!", "tortillaTank")) == match_key(yap("ww", "tortillaTank"))
    dedup = Dedup()
    first, _ = dedup.update(10.0, [yap("WW", "tortillaTank")])
    again, better = dedup.update(11.5, [yap("ww", "tortillaTank")])
    assert len(first) == 1 and again == []


def test_said_again_later_and_still_on_screen_is_stored_once_more_not_every_frame():
    """#129: on a tie the alignment took the old "Group up!", which the fade rule then refused."""
    dedup = Dedup()
    dedup.update(300.0, [yap("Group up!", "zappy", kind="comms")])  # long ago
    stored = len(dedup.update(399.0, [yap("Group up!", "zappy", kind="comms")])[0])
    for t in (399.5, 401.25, 402.75, 406.5):  # the same line, still on screen
        stored += len(dedup.update(t, [yap("Group up!", "zappy", kind="comms")])[0])
    assert stored == 1


def test_an_older_line_read_more_exactly_doesnt_steal_the_match():
    """#134: "Group up! ◇" long ago, "Group up!" now: the line on screen is the new one."""
    dedup = Dedup()
    dedup.update(300.0, [yap("Group up! ◇", "zappy", kind="comms")])
    stored = len(dedup.update(399.0, [yap("Group up!", "zappy", kind="comms")])[0])
    for t in (400.5, 402.0):  # the same line, now read with its icon
        stored += len(dedup.update(t, [yap("Group up! ◇", "zappy", kind="comms")])[0])
    assert stored == 1

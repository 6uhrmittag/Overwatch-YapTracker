"""Icons get their name back (#121): a "◇" becomes "[icon:thumbs-up]" where the line's picture
shows an icon the library knows, on new lines and on stored ones."""

import time

import cv2
import numpy as np
import pytest

from yaptracker import glyphs, icons, images
from yaptracker.capture.source import Region
from yaptracker.dedup import text_key
from yaptracker.lines import LinePictures
from yaptracker.matches import MatchTracker
from yaptracker.ocr.engine import OcrLine
from yaptracker.pause import Pause
from yaptracker.read_again import ReadAgain, name_icons_once
from yaptracker.reader import ChatReader
from yaptracker.store.repo import Store

T0 = time.mktime((2026, 11, 22, 20, 0, 0, 0, 0, -1))
BOX = Region(64, 100, 400, 38)
NAMES = ["fall-back", "group-up", "heal", "thumbs-up"]


def shape(name, scale=1.0):
    template = images.read(icons.FOLDER / f"{name}.png")[:, :, 0]
    size = (round(template.shape[1] * scale), round(template.shape[0] * scale))
    return cv2.resize(template, size, interpolation=cv2.INTER_AREA)


def frame(*drawn, height=300, ground=40, white=255, scale=1.0):
    """A chat frame: a map that isn't flat, cyan "text", and icons as (name, x, y)."""
    rng = np.random.default_rng(7)
    image = rng.integers(ground - 15, ground + 15, (height, 700, 3)).astype(np.uint8)
    image[BOX.y + 8 : BOX.y + 30, 70:380] = (230, 220, 20)  # the line's text, coloured
    for name, x, y in drawn:
        icon = shape(name, scale)
        h, w = icon.shape
        spot = image[y : y + h, x : x + w]
        spot[icon > 127] = white
    return image


def row(image):
    return image[BOX.y - 2 : BOX.y + BOX.height + 2]


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("scale", [0.75, 1.0, 1.5])
def test_every_icon_is_named_at_every_window_size(name, scale):
    image = frame((name, 400, 30), height=120, scale=scale)
    assert icons.find(image) == [name]


def test_a_mark_gets_its_name_also_faded_and_with_its_tip_cut_off():
    """The thumb is taller than the text: the line's picture cuts its tip. A fading line is grey."""
    picture = row(frame(("thumbs-up", 400, BOX.y - 6), white=150))
    assert picture.shape[0] < shape("thumbs-up").shape[0] + 4
    assert icons.name("Thanks! ◇", picture) == "Thanks! [icon:thumbs-up]"


def test_what_isnt_surely_a_known_icon_stays_a_mark():
    nothing = row(frame())
    one = row(frame(("heal", 400, BOX.y)))
    bright = row(frame(("heal", 400, BOX.y), ground=235))  # a white map: can't tell
    assert icons.name("gg ◇", nothing) == "gg ◇"
    assert icons.name("My ◇ is ◇ ready", one) == "My ◇ is ◇ ready"  # which of the two?
    assert icons.name("love u ◇", bright) == "love u ◇"
    assert icons.name("love u ◇", None) == "love u ◇"  # no picture kept
    assert icons.name("no mark", one) == "no mark"


def test_two_icons_are_named_in_reading_order_also_on_a_wrapped_line():
    one_row = frame(("heal", 500, 30), ("fall-back", 300, 34), height=110)
    wrapped = frame(("heal", 100, 76), ("fall-back", 500, 34), height=130)
    assert icons.name("a ◇ b ◇", one_row) == "a [icon:fall-back] b [icon:heal]"
    assert icons.name("a ◇ b ◇", wrapped) == "a [icon:fall-back] b [icon:heal]"
    uneven = frame(("heal", 100, 21), ("fall-back", 300, 25), height=70)  # a few px apart
    assert icons.find(uneven) == ["heal", "fall-back"]


def test_a_named_icon_still_counts_as_a_mark_everywhere_else():
    named = "Thanks! [icon:thumbs-up]"
    assert glyphs.has_glyphs(named) and glyphs.unnamed(named) == "Thanks! ◇"
    assert text_key("Pickle", named) == text_key("Pickle", "Thanks! ◇")  # readings still match


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def test_a_new_line_is_stored_with_its_icon_named_and_keeps_the_name(store):
    """Read again over a bright map, the icon can't be told: the name it has stays."""
    seen, bright = frame(("thumbs-up", 480, BOX.y - 2)), frame(ground=235)
    reads = {id(seen): [OcrLine("Pickle (Moira): Thanks!", 0.90, BOX)]}
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    reader = ChatReader(lambda image: reads[id(image)], store, tracker)
    (yap,) = reader.read_frame(T0, seen)
    (message,) = store.messages(tracker.match_id)
    assert (message.text, bool(message.has_glyphs)) == ("Thanks! [icon:thumbs-up]", True)
    assert [m.id for m in store.search("thanks")] == [message.id]
    assert yap.best.text == "Thanks! ◇"  # readings are compared as they were read
    # a better reading of it (live or the tidy-up) from a frame that doesn't show the icon
    assert reader._named(yap, bright, message)["text"] == "Thanks! [icon:thumbs-up]"
    assert reader._named(yap, bright)["text"] == "Thanks! [icon:thumbs-up]"  # by its words


def test_stored_lines_get_their_icons_named_once_from_their_pictures(store, tmp_path):
    pictures = LinePictures(tmp_path / "lines")
    match = store.start_match(store.start_session(T0), T0, "heroselect", "QUICK PLAY")

    def saved(n, text, image):
        message = store.add_message(ts=T0 + n, channel="team", text=text, speaker_raw="Pickle",
                                    hero="Moira", match_id=match, has_glyphs=True)  # fmt: skip
        pictures.save(message, T0 + n, image, BOX)
        return message

    healing = saved(1, "I need healing! ◇", frame(("heal", 480, BOX.y)))
    unknown = saved(2, "love u ◇", frame())
    by_hand = saved(3, "Fall back! ◇", frame(("fall-back", 480, BOX.y + 5)))
    store.edit_message(by_hand, "Fall back!! ◇", T0 + 9)
    gone = store.add_message(ts=T0 + 4, channel="team", text="Group up! ◇", match_id=match,
                             has_glyphs=True)  # its picture was cleaned up  # fmt: skip
    again = ReadAgain(store, pictures, lambda image: [], idle=lambda: True)
    done = []
    name_icons_once(again, store, lambda: max(done, default=0), done.append)
    while again.run_once():
        pass
    texts = {m.id: (m.text, bool(m.has_glyphs)) for m in store.messages(match)}
    assert texts[healing] == ("I need healing! [icon:heal]", True)
    assert texts[unknown] == ("love u ◇", True)
    assert texts[by_hand] == ("Fall back!! ◇", True)  # fixed by hand: never touched
    assert texts[gone] == ("Group up! [icon:group-up]", True)  # no picture: by its words
    assert done == [icons.LIBRARY]
    name_icons_once(again, store, lambda: max(done, default=0), done.append)
    assert done == [icons.LIBRARY] and not again.run_once()  # not again with the same library


def test_read_again_keeps_a_name_and_names_what_it_reads(store, tmp_path):
    pictures = LinePictures(tmp_path / "lines")
    match = store.start_match(store.start_session(T0), T0, "heroselect", "QUICK PLAY")
    message = store.add_message(ts=T0, channel="team", text="l need heaIing! ◇", hero="Moira",
                                speaker_raw="Pickle", match_id=match, ocr_confidence=0.6,
                                has_glyphs=True)  # fmt: skip
    pictures.save(message, T0, frame(("heal", 480, BOX.y)), BOX)
    best = [OcrLine("Pickle (Moira): I need healing!", 0.98, Region(64, 2, 400, 38))]
    again = ReadAgain(store, pictures, lambda image: best, idle=lambda: True)
    again.line(message)
    again.run_once()
    assert store.message(message).text == "I need healing! [icon:heal]"
    job = again.line(message)  # once more: the same reading isn't "better" for its name's letters
    again.run_once()
    assert job.better == [] and store.message(message).text == "I need healing! [icon:heal]"


def test_the_four_callouts_are_named_by_their_words_whatever_the_picture_shows():
    """#121, second slice: a bright map behind the icon or an old picture cut at the text."""
    from yaptracker.parser import ICON_CALLOUTS

    assert set(icons.BY_TEXT) == ICON_CALLOUTS  # the same four the parser marks (#259)
    bright = row(frame(ground=235))
    assert icons.name("Thanks! ◇", bright) == "Thanks! [icon:thumbs-up]"
    assert icons.name("I need healing! ◇", None) == "I need healing! [icon:heal]"
    assert icons.name("Group up! ◇", row(frame())) == "Group up! [icon:group-up]"
    assert icons.name("Fall back! ◇", None) == "Fall back! [icon:fall-back]"
    assert icons.by_text("thanks! ◇") == "thanks! [icon:thumbs-up]"  # the words as they are
    for other in ("Thanks!", "Thanks! ◇ ◇", "Thanks! ◇ gg", "Hello! ◇", "Fall back! ◇ I'm "
                  "waiting to respawn! (12s)", "Thanks! [icon:thumbs-up]"):  # fmt: skip
        assert icons.by_text(other) is None, other


def test_a_callout_parsed_from_ocr_is_stored_named_without_its_picture(store):
    from yaptracker.parser import parse

    (line,) = parse([OcrLine("Pickle (Moira): I need healing!", 0.95, BOX)])
    assert line.text == "I need healing! ◇"
    assert icons.name(line.text, None) == "I need healing! [icon:heal]"


def test_known_icons_show_as_emoji_the_text_keeps_the_tag():
    """#121 (Marv, 2026-11-24): one table, the tag stays stored, people read the emoji."""
    assert glyphs.shown("Thanks! [icon:thumbs-up]") == "Thanks! \U0001f44d"
    assert glyphs.shown("[icon:heal][icon:group-up] [icon:fall-back]") == "➕\U0001f4cd ⏪"
    assert glyphs.shown("gg [icon:someday] ◇") == "gg [icon:someday] ◇"  # no emoji yet
    assert set(glyphs.EMOJI) == set(icons.BY_TEXT.values())  # every named icon has one


def test_a_search_hit_inside_a_tag_highlights_the_emoji():
    from yaptracker.ui.search import marked_html

    assert marked_html("Thanks! [icon:\x01thumbs\x02-up]") == (
        'Thanks! <mark class="yt-hit">\U0001f44d</mark>'
    )
    assert marked_html("\x01Thanks\x02! [icon:thumbs-up]") == (
        '<mark class="yt-hit">Thanks</mark>! \U0001f44d'
    )

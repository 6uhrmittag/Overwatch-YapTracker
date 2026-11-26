"""Live chat into the database (#108): the real pipeline with a fake OCR and a real store."""

import json
import logging
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from yaptracker.capture.source import Region
from yaptracker.identity import Identity
from yaptracker.matches import MatchTracker
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import ChatLine
from yaptracker.pause import Pause
from yaptracker.reader import ChatReader
from yaptracker.store.repo import Store

REPLAY = Path(__file__).parent / "fixtures" / "dedup" / "esperanca-match-end.json"
BLACK = np.zeros((395, 615, 3), np.uint8)  # the fixture has OCR text only, no pictures


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def line(text, y=10, confidence=0.99):
    return OcrLine(text, confidence, Region(64, y, 400, 24))


def reader_for(store, reads, **kwargs):
    """reads: what the fake OCR returns for each image, by id()."""
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(1000.0)
    return ChatReader(lambda image: reads[id(image)], store, tracker, **kwargs), tracker


def test_four_real_minutes_end_up_in_the_database_once_with_who_said_it(store):
    frames = json.loads(REPLAY.read_text(encoding="utf-8"))["frames"]
    shots = [(frame["t"], BLACK.copy(), frame["ocr"]) for frame in frames]
    reads = {
        id(image): [OcrLine(o["text"], o["confidence"], Region(*o["box"])) for o in ocr]
        for _, image, ocr in shots
    }
    me_and_crew = Identity(me=("tortillaTank",), crew=("NoodleBonk",))
    reader, tracker = reader_for(store, reads, identity=lambda: me_and_crew)
    for t, image, _ in shots:
        reader.read_frame(1000.0 + t, image)
    stored = store.messages(tracker.match_id)
    assert len(stored) == 14
    assert [(m.speaker_raw, m.text, m.role) for m in stored[:4]] == [
        ("NoodleBonk", "Hello!", "crew"),
        ("tortillaTank", "Thanks! [icon:thumbs-up]", "me"),  # its icon (#259), named (#121)
        ("MaybeMaybe", "Enemy Tracer!", None),
        ("tortillaTank", "tracer come heereee I have cookies", "me"),
    ]
    assert (stored[0].channel, stored[0].hero) == ("team", "Sierra")  # comms wheel
    assert stored[-1].channel == "system" and stored[-1].text == "You endorsed MaybeMaybe!"
    assert [m.text for m in store.search("cookies")] == ["tracer come heereee I have cookies"]


def test_a_better_reading_updates_the_stored_line(store):
    glitch, good1, good2 = BLACK.copy(), BLACK.copy(), BLACK.copy()
    reads = {id(glitch): [line("[NoodleBonk]: Oops XD EM PORTUGAL", confidence=0.99)],
             id(good1): [line("[NoodleBonk]: Oops XD", confidence=0.96)],
             id(good2): [line("[NoodleBonk]: Oops XD", confidence=0.97)]}  # fmt: skip
    reader, tracker = reader_for(store, reads)
    for t, image in enumerate([glitch, good1, good2]):
        reader.read_frame(1000.0 + t, image)
    assert [m.text for m in store.messages(tracker.match_id)] == ["Oops XD"]
    assert store.search("portugal") == []  # the search index follows the update


def test_every_stored_and_every_improved_line_is_offered_for_a_second_look(store):
    """#637: the reader only hands (message id, when, the line's readings) on; the AI worker
    decides. Offered again when a reading changes: readings that disagree show up only then."""
    glitch, good1, good2 = BLACK.copy(), BLACK.copy(), BLACK.copy()
    reads = {id(glitch): [line("[NoodleBonk]: Oops XD EM PORTUGAL", confidence=0.99)],
             id(good1): [line("[NoodleBonk]: Oops XD", confidence=0.96)],
             id(good2): [line("[NoodleBonk]: Oops XD", confidence=0.97)]}  # fmt: skip
    offered = []
    reader, tracker = reader_for(
        store, reads, doubtful=lambda message_id, ts, yap: offered.append((message_id, ts))
    )
    for t, image in enumerate([glitch, good1, good2]):
        reader.read_frame(1000.0 + t, image)
    (stored,) = store.messages(tracker.match_id)
    assert offered[0] == (stored.id, 1000.0) and len(offered) >= 2


def test_a_failing_second_look_never_fails_a_read(store):
    image = BLACK.copy()
    reads = {id(image): [line("[NoodleBonk]: hi")]}

    def broken(*args):
        raise RuntimeError("the AI queue broke")

    reader, tracker = reader_for(store, reads, doubtful=broken)
    reader.read_frame(1000.0, image)
    assert [m.text for m in store.messages(tracker.match_id)] == ["hi"]


def test_new_chat_starts_the_match_and_nothing_is_read_while_paused(store):
    image = BLACK.copy()
    pause = Pause()
    reader, tracker = reader_for(store, {id(image): [line("[zappy]: gl hf")]},
                                 paused=lambda: pause.paused)  # fmt: skip
    pause.pause()
    assert reader.read_frame(1000.0, image) == [] and tracker.match_id is None
    pause.resume()
    reader.read_frame(1001.0, image)
    assert [m.text for m in store.messages(tracker.match_id)] == ["gl hf"]


def test_if_ocr_falls_behind_only_the_newest_frame_waits(store):
    first, skipped, newest = BLACK.copy(), BLACK.copy(), BLACK.copy()
    reading, release, read = threading.Event(), threading.Event(), []

    def slow_ocr(image):
        read.append(image)
        if image is first:
            reading.set()
            release.wait(5)
        return []

    tracker = MatchTracker(store, Pause())
    reader = ChatReader(slow_ocr, store, tracker)
    reader.start()
    reader.offer(first)
    assert reading.wait(5)
    reader.offer(skipped)  # arrives while the first is still being read ...
    reader.offer(newest)  # ... and is replaced by a newer one
    release.set()
    reader.stop()  # waits for the thread
    assert len(read) == 2 and read[0] is first and read[1] is newest  # never `skipped`


def test_a_failing_ocr_is_logged_and_the_chat_still_counts_for_the_match(store, caplog):
    def broken(image):
        raise RuntimeError("no OCR today")

    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(1000.0)
    reader = ChatReader(broken, store, tracker)
    reader.start()
    reader.offer(BLACK)
    reader.stop()
    assert "reading the chat failed" in caplog.text
    assert tracker.match_id is not None


def test_every_read_frame_goes_to_the_debug_samples_with_its_ocr(store):
    image, seen = BLACK.copy(), []
    reader, _ = reader_for(store, {id(image): [line("[zappy]: gl hf", confidence=0.7)]},
                           on_read=lambda *args: seen.append(args))  # fmt: skip
    reader.read_frame(1000.0, image)
    ((ts, frame, ocr, lines, new, unstored),) = seen
    assert unstored == []  # nothing seen-but-not-stored (#425)
    assert (ts, frame is image, ocr[0].text, lines[0].speaker) == (1000.0, True, "[zappy]: gl hf",
                                                                    "zappy")  # fmt: skip
    assert [y.best.text for y in new] == ["gl hf"]


def test_reads_keep_a_gap_and_the_newest_frame_is_the_one_read(store):
    import time

    frames = [BLACK.copy() for _ in range(12)]
    read = []
    tracker = MatchTracker(store, Pause())
    reader = ChatReader(lambda image: read.append(image) or [], store, tracker, min_gap_s=0.2)
    reader.start()
    for frame in frames:  # a burst: 12 changed frames in 0.36 s
        reader.offer(frame)
        time.sleep(0.03)
    time.sleep(0.25)
    reader.stop()
    assert 2 <= len(read) <= 4  # not 12
    assert read[-1] is frames[-1]  # the last change is never lost


def test_every_stored_line_keeps_its_picture(store, tmp_path):
    from yaptracker.lines import LinePictures

    frames = json.loads(REPLAY.read_text(encoding="utf-8"))["frames"]
    shots = [(frame["t"], np.full((395, 615, 3), 60, np.uint8), frame["ocr"]) for frame in frames]
    reads = {
        id(image): [OcrLine(o["text"], o["confidence"], Region(*o["box"])) for o in ocr]
        for _, image, ocr in shots
    }
    pictures = LinePictures(tmp_path / "lines")
    reader, tracker = reader_for(store, reads, pictures=pictures)
    for t, image, _ in shots:
        reader.read_frame(1000.0 + t, image)
    stored = store.messages(tracker.match_id)
    saved = sorted(int(p.stem) for p in (tmp_path / "lines").rglob("*.webp"))
    assert saved == sorted(m.id for m in stored) and len(saved) == 14  # one each, none extra


def test_every_line_belongs_to_a_player_except_mine(store):
    from yaptracker.players import PlayerMatcher

    frames = json.loads(REPLAY.read_text(encoding="utf-8"))["frames"]
    shots = [(frame["t"], BLACK.copy(), frame["ocr"]) for frame in frames]
    reads = {
        id(image): [OcrLine(o["text"], o["confidence"], Region(*o["box"])) for o in ocr]
        for _, image, ocr in shots
    }
    me = Identity(me=("tortillaTank",))
    reader, tracker = reader_for(store, reads, identity=lambda: me,
                                 players=PlayerMatcher(store, lambda: me))  # fmt: skip
    for t, image, _ in shots:
        reader.read_frame(1000.0 + t, image)
    names = dict(store._read("SELECT id, display_name FROM players"))
    assert sorted(names.values()) == ["MaybeMaybe", "NoodleBonk", "SirPeelsALot", "mossyfox",
                                      "zappy"]  # fmt: skip
    for m in store.messages(tracker.match_id):
        if m.speaker_raw == "tortillaTank" or m.channel == "system":
            assert m.player_id is None
        else:
            assert names[m.player_id] == m.speaker_raw


def test_a_friend_coming_online_is_no_familiar_face(store):
    """#26: "[x] started playing Overwatch." is the friends list, not someone in the match."""
    online, typed = BLACK.copy(), BLACK.copy()
    reads = {id(online): [line("[gremlin.exe] started playing Overwatch.")],
             id(typed): [line("[gremlin.exe] started playing Overwatch."),
                         line("[gremlin.exe]: hi again", y=50)]}  # fmt: skip
    heard = []
    reader, _ = reader_for(store, reads, on_player=lambda player, *_: heard.append(player))
    reader.read_frame(1000.0, online)
    assert heard == []
    reader.read_frame(1001.0, typed)
    assert len(heard) == 1


def test_a_friend_list_notice_is_nobody_met(store):
    """#306: "[x] stopped playing Overwatch." fired a card. A system line never links a player:
    no card, no new player, no "last seen"."""
    from yaptracker.players import PlayerMatcher

    hello, notices = BLACK.copy(), BLACK.copy()
    reads = {id(hello): [line("[Pal]: hi")],
             id(notices): [line("[Pal]: hi"), line("[Pal] stopped playing Overwatch.", y=50),
                           line("[Stranger] started spectating.", y=100)]}  # fmt: skip
    heard = []
    reader, tracker = reader_for(store, reads, players=PlayerMatcher(store, lambda: Identity()),
                                 on_player=lambda player, *_: heard.append(player))  # fmt: skip
    reader.read_frame(1000.0, hello)
    reader.read_frame(1005.0, notices)  # the hello still on screen
    assert len(heard) == 1  # the hello
    assert store._read("SELECT display_name, last_seen FROM players") == [("Pal", 1000.0)]
    assert [(m.channel, m.player_id) for m in store.messages(tracker.match_id)][1:] == [
        ("system", None),
        ("system", None),
    ]


CHAT_CLOSED = Path(__file__).parent / "fixtures" / "dedup" / "179-chat-closed.json"


def test_after_sending_a_line_the_history_on_screen_is_not_new(store):
    """#179 replay: a hello, the chat opened (history shows), a line sent (history still shows,
    prompt gone): only the sent line is new. It was stored with a second hello and four old
    post-game lines."""
    frames = json.loads(CHAT_CLOSED.read_text(encoding="utf-8"))["frames"]
    shots = [(frame["t"], BLACK.copy(), frame["ocr"]) for frame in frames]
    reads = {id(image): [OcrLine(o["text"], o["confidence"], Region(*o["box"])) for o in ocr]
             for _, image, ocr in shots}  # fmt: skip
    reader, tracker = reader_for(store, reads, identity=lambda: Identity(me=("tortillaTank",)))
    for t, image, _ in shots:
        reader.read_frame(1000.0 + t, image)
    assert [m.text for m in store.messages(tracker.match_id)] == ["Hello!", "haili gaaaang"]


def test_lines_on_screen_when_a_match_starts_stay_with_the_match_before(store):
    """#179: a line that was already on screen before hero select is the old match's; one typed
    after it is the new match's."""
    frames = [BLACK.copy() for _ in range(4)]
    game, gg, glhf = "[Pickle]: what a game", "[Pickle]: gg", "[Moon]: gl hf"
    reads = {id(frames[0]): [line(gg, 300)],
             id(frames[1]): [line(game, 260), line(gg, 300)],
             id(frames[2]): [line(game, 300)],
             id(frames[3]): [line(game, 260), line(glhf, 300)]}  # fmt: skip
    reader, tracker = reader_for(store, reads)
    tracker.new_match(1000.0, source="heroselect")  # a real match: only chat would be #307's
    reader.read_frame(1000.0, frames[0])  # "gg" in match 1
    reader.read_frame(1001.0, frames[1])  # "what a game" above it: not new, but on screen
    first = tracker.match_id
    tracker.new_match(1300.0, source="heroselect")  # the next match, minutes later
    reader.read_frame(1302.0, frames[2])  # "gg" gone, "what a game" read as new
    reader.read_frame(1304.0, frames[3])  # typed in hero select
    assert [m.text for m in store.messages(first)] == ["gg", "what a game"]
    assert [m.text for m in store.messages(tracker.match_id)] == ["gl hf"]


def test_a_friend_notice_in_the_menu_starts_no_match(store):
    """#417: "2 friends playing Overwatch." in the menu started match 131, which never ended:
    Update now waited for it, capture ran at the in-match rate. System lines start nothing;
    typed chat still does (#307)."""
    menu, chat = BLACK.copy(), BLACK.copy()
    friends = line("2 friends playing Overwatch.")
    reads = {id(menu): [friends], id(chat): [friends, line("[Pip]: anyone up?", y=40)]}
    reader, tracker = reader_for(store, reads)
    reader.read_frame(1000.0, menu)
    assert tracker.match_id is None and not tracker.running
    assert [m.text for m in store.messages_outside_matches()] == ["2 friends playing Overwatch."]
    reader.read_frame(1010.0, chat)
    assert tracker.running
    assert [m.text for m in store.messages(tracker.match_id)] == ["anyone up?"]


def test_a_line_missed_after_a_match_goes_to_that_match_in_its_place(store):
    """#423: read later between two stored lines (the next match may run by then), it's stored
    in the match of the line above it, sorted right after it."""
    first, second, later = BLACK.copy(), BLACK.copy(), BLACK.copy()
    reads = {id(first): [line("[Void]: cute Mei skin so yeah")],
             id(second): [line("[Void]: cute Mei skin so yeah"), line("You endorsed Bo!", y=50)],
             id(later): [line("[Void]: cute Mei skin so yeah"), line("[Void]: Tracks", y=50),
                         line("You endorsed Bo!", y=90)]}  # fmt: skip
    reader, tracker = reader_for(store, reads)
    reader.read_frame(1000.0, first)
    reader.read_frame(1001.0, second)  # this read missed "Tracks"
    after = tracker.match_id
    tracker.end_match(1002.0, "victory")
    tracker.new_match(1004.0, source="heroselect")  # the next match starts
    reader.read_frame(1005.0, later)  # read twice before it counts (#432)
    reader.read_frame(1006.0, later)
    assert [m.text for m in store.messages(after)] == ["cute Mei skin so yeah", "Tracks",
                                                       "You endorsed Bo!"]  # fmt: skip
    assert store.messages(tracker.match_id) == []


def chat(kind, text, speaker=None):
    channel = "system" if kind == "system" else "match"
    return ChatLine(kind, channel, text, 0.99, Region(64, 10, 400, 24), speaker=speaker)


def test_seen_but_not_stored_counts_only_lines_really_missing_and_each_once(store, caplog):
    """#504: an evening said 3, one was missing: a stored line (junk glued on, or a minute out
    of Dedup's sight) and the same line with and without a full stop each counted."""
    caplog.set_level(logging.INFO, "yaptracker.reader")
    first = BLACK.copy()
    reads = {id(first): [line("You endorsed Bo! NEXT TIER: 4071/50000"),
                         line("[Pip]: nice shot, that was amazing", y=50)]}  # fmt: skip
    seen = []
    reader, tracker = reader_for(store, reads, on_read=lambda *args: seen.append(args[-1]))
    reader.read_frame(1000.0, first)
    assert len(store.messages(tracker.match_id)) == 2
    missing = chat("message", "have fun all", "Bo")  # the only line really missing
    unstored = [
        [
            chat("system", "You endorsed Bo!"),
            chat("message", "nice shot that was amazing", "Pip"),
            missing,
        ],  # fmt: skip
        [chat("message", "have fun all.", "Bo")],  # the same line, two minutes later
        [chat("message", "have fum all", "B0")],  # and read a bit wrong
        [chat("message", "nice shot", "Pip")],  # two words: not taken for the start of it
    ]
    for n, rows in enumerate(unstored):
        reader._dedup = SimpleNamespace(
            update=lambda ts, lines: ([], []), unstored=rows, recent=[],
            piece_of=lambda row: None, adopt=lambda row: None, misread_of=lambda row: None,
            whole_of=lambda row: None,
        )  # fmt: skip
        reader.read_frame(1100.0 + 100 * n, first)  # Dedup is faked: these rows only
    assert [[r.text for r in rows] for rows in seen[1:]] == [
        ["have fun all"],
        [],
        [],
        ["nice shot"],
    ]
    assert caplog.text.count("never stored") == 2
    said = "1 line(s) seen twice but never stored: Bo: have fun all (older than every line I"
    assert said + " know)\n" in caplog.text  # the reason per line (#602)


def test_seen_but_not_stored_once_per_match_also_when_kept_frames_take_turns(store):
    """#504 review: kept frames of the match before and live frames alternate; a line stored
    outside any match (the menu) counts as stored."""
    reader, _ = reader_for(store, {})
    store.add_message(ts=1000.0, channel="system", text="You have joined a group!")
    joined, gg = chat("system", "You have joined a group!"), chat("message", "gg", "Bo")
    assert reader._really_unstored(1010.0, [joined], None) == []
    assert reader._really_unstored(1010.0, [gg], 5) == [gg]
    assert reader._really_unstored(1020.0, [gg], 6) == [gg]  # another match: counted there
    assert reader._really_unstored(1030.0, [gg], 5) == []  # match 5 still knows it
    assert reader._really_unstored(1040.0, [gg], 6) == []


def _reopened(store, **kwargs):
    """Three lines read; then a gap in which two more were said and scrolled by unread; then the
    chat re-opened: the lost ones show above the newest known line, the older ones are out of
    the box. Not between two known lines, so #423 didn't keep them."""
    before, after, again = BLACK.copy(), BLACK.copy(), BLACK.copy()
    known = ["[Pip]: hello there", "[Bo]: glhf everyone", "[Kim]: nice shot"]
    opened = [
        line("[Zed]: very silly game", y=10),
        line("[Bo]: Chill Sierra, you were 85 %", y=50),
        line("[Kim]: nice shot", y=90),
        line("[Match] ", y=130),
    ]  # its prompt: the box is open
    reads = {id(before): [line(text, y=10 + 40 * n) for n, text in enumerate(known[:2])],
             id(after): [line(text, y=10 + 40 * n) for n, text in enumerate(known)],
             id(again): opened}  # fmt: skip
    reader, tracker = reader_for(store, reads, **kwargs)
    reader.read_frame(1000.0, before)
    reader.read_frame(1300.0, after)  # "nice shot" came after the gap; two lines were lost
    return reader, tracker, again


def test_reopening_the_chat_after_a_gap_brings_the_lost_lines_back_once(store, caplog):
    """#602: Marv re-opened the chat to get a lost line back; it was seen twice, logged as
    'never stored', and dropped. Now it's stored: once, in its place."""
    caplog.set_level(logging.INFO, "yaptracker.reader")
    reader, tracker, again = _reopened(store)
    assert reader.read_frame(1310.0, again) == []  # read twice before it counts (#432)
    assert [yap.best.text for yap in reader.read_frame(1312.0, again)] == [
        "very silly game", "Chill Sierra, you were 85 %"]  # fmt: skip
    for ts in (1314.0, 1316.0, 1400.0):  # still on screen, and opened once more later
        assert reader.read_frame(ts, again) == []
    stored = store.messages(tracker.match_id)
    assert [(m.speaker_raw, m.text) for m in stored] == [
        ("Pip", "hello there"), ("Bo", "glhf everyone"), ("Zed", "very silly game"),
        ("Bo", "Chill Sierra, you were 85 %"), ("Kim", "nice shot")]  # fmt: skip
    assert stored[2].ts < stored[3].ts < stored[4].ts == 1300.0  # said before the line below
    assert "2 line(s) seen twice, stored now: Zed: very silly game; Bo: Chill Sierra" in caplog.text
    assert "never stored" not in caplog.text


def test_a_lost_line_seen_after_its_match_goes_to_that_match(store):
    reader, tracker, again = _reopened(store)
    played = tracker.match_id
    tracker.end_match(1302.0, "victory")
    tracker.new_match(1305.0, source="heroselect")
    reader.read_frame(1310.0, again)
    reader.read_frame(1312.0, again)
    assert len(store.messages(played)) == 5 and store.messages(tracker.match_id) == []


def test_history_from_before_anything_was_read_stays_out_and_the_log_says_why(store, caplog):
    """#179: rows above the oldest line known are the opened chat's old history, not lost
    lines: there's no known line they were said after."""
    caplog.set_level(logging.INFO, "yaptracker.reader")
    first, opened = BLACK.copy(), BLACK.copy()
    reads = {
        id(first): [line("[Pip]: hello there")],
        id(opened): [line("[Old]: from the match before"), line("[Pip]: hello there", y=50)],
    }
    reader, tracker = reader_for(store, reads)
    for ts, image in ((1000.0, first), (1002.0, opened), (1004.0, opened), (1006.0, opened)):
        reader.read_frame(ts, image)
    assert [m.text for m in store.messages(tracker.match_id)] == ["hello there"]
    assert caplog.text.count("never stored") == 1  # said once
    assert ("seen twice but never stored: Old: from the match before (older than every line I"
            " know)") in caplog.text  # fmt: skip


def test_a_longer_reading_of_a_line_stored_cut_is_no_second_line(store, caplog):
    caplog.set_level(logging.INFO, "yaptracker.reader")
    reader, tracker, again = _reopened(store)
    store.add_message(
        ts=900.0, match_id=tracker.match_id, channel="match", speaker_raw="Zed", text="very silly"
    )  # two words: "very silly game" is a line of its own
    store.add_message(
        ts=901.0,
        match_id=tracker.match_id,
        channel="match",
        speaker_raw="Bo",
        text="Chill Sierra, you",
    )  # three: the same line, stored cut
    reader.read_frame(1310.0, again)
    reader.read_frame(1312.0, again)
    assert [m.text for m in store.messages(tracker.match_id) if m.ts >= 1000.0] == [
        "hello there", "glhf everyone", "very silly game", "nice shot"]  # fmt: skip
    assert "Bo: Chill Sierra, you were 85 % (a piece of a stored line)" in caplog.text


def test_a_lost_line_is_also_kept_while_the_match_before_is_still_being_read(store):
    """Review: refused once for the backlog, it was never looked at again in that match. The
    live stream only adopts after a line it knows itself, so kept frames can't bring it."""
    from yaptracker.dedup import Dedup

    reader, tracker, again = _reopened(store)
    reader._kept_dedup = Dedup(ids=reader._dedup.ids)  # two streams side by side (#597)
    reader.read_frame(1310.0, again)
    reader.read_frame(1312.0, again)
    assert len(store.messages(tracker.match_id)) == 5


def _opened_chat(store, known: list[str], opened: list[str], **kwargs):
    """`known` read in one frame, then the opened chat showing `opened`, read three times."""
    first, again = BLACK.copy(), BLACK.copy()
    reads = {
        id(first): [line(text, y=10 + 40 * n) for n, text in enumerate(known)],
        id(again): [line(text, y=10 + 40 * n) for n, text in enumerate([*opened, "[Match] "])],
    }
    reader, tracker = reader_for(store, reads, **kwargs)
    reader.read_frame(1000.0, first)
    for ts in (1300.0, 1302.0, 1304.0):
        reader.read_frame(ts, again)
    return [m.text for m in store.lines_since(0.0)], tracker


def test_a_known_line_read_a_little_wrong_is_not_stored_again(store, caplog):
    """Review: "[Plp]: gg" is under the bar for "[Pip]: gg" (83 of 85) and was adopted next to
    it, with a player "Plp"."""
    caplog.set_level(logging.INFO, "yaptracker.reader")
    known = ["[Pip]: gg", "[Bo]: two words here", "[Kim]: three"]
    texts, _ = _opened_chat(store, known, ["[Plp]: gg", "[Bo]: two words here", "[Kim]: three"])
    assert texts == ["gg", "two words here", "three"]
    assert "Plp: gg (may be a known line read wrong)" in caplog.text


def test_a_cut_reading_of_a_line_stored_whole_is_not_a_second_line(store, caplog):
    """Review: "so please n" (#432's own example) passed the three-whole-words rule."""
    caplog.set_level(logging.INFO, "yaptracker.reader")
    known = ["[Zed]: hi", "[Pip]: so please not the mei again", "[Bo]: ok fine", "[Kim]: lol"]
    texts, _ = _opened_chat(store, known, ["[Pip]: so please n", "[Bo]: ok fine", "[Kim]: lol"])
    assert texts == ["hi", "so please not the mei again", "ok fine", "lol"]
    assert "Pip: so please n (a piece of a stored line)" in caplog.text


def test_a_line_like_one_stored_long_ago_stays_out_and_the_log_says_so(store, caplog):
    """Review: filtered by the far look-back, it vanished without a word."""
    caplog.set_level(logging.INFO, "yaptracker.reader")
    reader, tracker, again = _reopened(store)
    store.add_message(
        ts=1000.5,
        match_id=tracker.match_id,
        channel="match",
        speaker_raw="Zed",
        text="very silly game",
    )  # 20 min before it's seen again
    reader.read_frame(2200.0, again)
    reader.read_frame(2202.0, again)
    assert [m.text for m in store.messages(tracker.match_id)].count("very silly game") == 1
    assert "Zed: very silly game (like a line stored earlier)" in caplog.text


def test_a_lost_line_above_a_menu_line_stays_outside_matches_like_it(store):
    """Review: the line below it was stored outside any match; it went into the running one."""
    reader, tracker, again = _reopened(store)
    for message in store.messages(tracker.match_id):
        store._write("UPDATE chat_messages SET match_id = NULL WHERE id = ?", (message.id,))
    reader.read_frame(1310.0, again)
    reader.read_frame(1312.0, again)
    assert store.messages(tracker.match_id) == []
    assert len(store.lines_since(0.0)) == 5


def test_debug_samples_get_the_kept_lines_as_new_and_only_the_refused_as_unstored(store):
    seen = []
    reader, tracker, again = _reopened(store, on_read=lambda *args: seen.append(args[-2:]))
    reader.read_frame(1310.0, again)
    reader.read_frame(1312.0, again)
    new, unstored = seen[-1]
    assert [yap.best.text for yap in new] == ["very silly game", "Chill Sierra, you were 85 %"]
    assert unstored == []


def test_a_whole_reading_seen_twice_completes_the_line_stored_cut(store, caplog):
    """#609: refused as "a piece of a stored line" since #602, the stored line stayed cut."""
    caplog.set_level(logging.INFO, "yaptracker.reader")
    known = ["[Zed]: hi", "[Pip]: bruh my mei is trolling half the", "[Bo]: ok fine", "[Kim]: lol"]
    opened = ["[Pip]: bruh my mei is trolling half the game, he walls me", "[Bo]: ok fine",
              "[Kim]: lol"]  # fmt: skip
    texts, _ = _opened_chat(store, known, opened)
    assert texts == ["hi", "bruh my mei is trolling half the game, he walls me", "ok fine", "lol"]
    assert "1 line(s) stored cut, now whole: Pip: bruh my mei is trolling half the game" in (
        caplog.text)  # fmt: skip
    assert "never stored" not in caplog.text


def test_a_line_cut_in_the_middle_of_a_word_is_completed_too(store):
    known = ["[Zed]: hi", "[Pip]: have a much Uw", "[Bo]: ok fine"]
    texts, _ = _opened_chat(store, known, ["[Pip]: have a much UwU gameeeee", "[Bo]: ok fine"])
    assert texts == ["hi", "have a much UwU gameeeee", "ok fine"]


def test_two_short_words_complete_nothing(store):
    known = ["[Zed]: hi", "[Pip]: nice shot", "[Bo]: ok fine"]
    texts, _ = _opened_chat(store, known, ["[Pip]: nice shot that was", "[Bo]: ok fine"])
    assert "nice shot" in texts  # "nice shot that was" is a line of its own, as typed lines are


def test_a_cut_line_with_map_text_glued_on_is_completed_too(store):
    """Review: the row counted as completing it, but the stored text stayed."""
    known = ["[Zed]: hi", "[Pip]: good game everyone TOURING EM", "[Bo]: ok fine"]
    opened = ["[Pip]: good game everyone and thanks a lot friends", "[Bo]: ok fine"]
    texts, _ = _opened_chat(store, known, opened)
    assert texts == ["hi", "good game everyone and thanks a lot friends", "ok fine"]

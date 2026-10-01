"""Live chat into the database (#108): the real pipeline with a fake OCR and a real store."""

import json
import threading
from pathlib import Path

import numpy as np
import pytest

from yaptracker.capture.source import Region
from yaptracker.identity import Identity
from yaptracker.matches import MatchTracker
from yaptracker.ocr.engine import OcrLine
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
        ("tortillaTank", "Thanks!", "me"),
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
    ((ts, frame, ocr, lines, new),) = seen
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

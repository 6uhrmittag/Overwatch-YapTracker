"""Read after the match (#335): no OCR during the match, then the kept frames in order, with
their real timestamps, into their match; the same lines as reading live."""

import json
import logging
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from yaptracker.capture.source import Region
from yaptracker.familiar import FamiliarFaces
from yaptracker.later import LaterFrames, lost_span
from yaptracker.matches import MatchTracker
from yaptracker.ocr.engine import OcrLine
from yaptracker.pause import Pause
from yaptracker.reader import ChatReader
from yaptracker.store.repo import Store

REPLAY = Path(__file__).parent / "fixtures" / "dedup" / "esperanca-match-end.json"
T0 = 1000.0


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def frame(size=100):
    return np.zeros((size, 10, 3), np.uint8)  # 3000 bytes at size 100


def replay():
    """(t, image, ocr lines) of four real minutes of chat; OCR text only, no pictures."""
    shots = []
    for f in json.loads(REPLAY.read_text(encoding="utf-8"))["frames"]:
        lines = [OcrLine(o["text"], o["confidence"], Region(*o["box"])) for o in f["ocr"]]
        shots.append((T0 + f["t"], np.zeros((395, 615, 3), np.uint8), lines))
    return shots


def stored(store, match_id):
    return [(m.ts, m.speaker_raw, m.text) for m in store.messages(match_id)]


def wait_for(done, timeout=10.0):
    end = time.monotonic() + timeout
    while not done():
        assert time.monotonic() < end, "the reader didn't get there in time"
        time.sleep(0.01)


def test_a_newer_frame_within_the_read_gap_replaces_the_kept_one():
    later = LaterFrames(lambda: 1.5, None)
    a, b, c = frame(), frame(), frame()
    later.add(T0, a, 1, "after")
    later.add(T0 + 1.0, b, 1, "after")  # newest wins, as in live reading
    later.add(T0 + 1.6, c, 1, "after")
    assert [k.image is b for k in (later.pop(),)] == [True]
    assert later.pop().image is c and later.pop() is None


def test_the_memory_cap_drops_the_frame_the_others_cover_best():
    later = LaterFrames(lambda: 0.0, None, cap_bytes=3 * 3000)
    for t in (0, 10, 11, 30):  # 11 is right after 10: dropping 10 loses the least
        later.add(T0 + t, frame(), 1, "after")
    assert [later.pop().ts - T0 for _ in range(3)] == [0, 11, 30]
    assert later.take_counts() == (4, 1)


def test_the_note_of_waiting_frames_survives_a_crash_and_goes_once_read(tmp_path):
    note = tmp_path / "unread-chat.json"
    later = LaterFrames(lambda: 0.0, note)
    later.add(T0, frame(), 1, "after")
    later.add(T0 + 30, frame(), 1, "after")  # written again: 10 s since the last note
    assert json.loads(note.read_text()) == {"first": T0, "last": T0 + 30}
    later.pop()
    later.pop()
    assert not note.exists()  # all read: nothing lost
    later.add(T0 + 60, frame(), 1, "after")
    assert lost_span(note) == (T0 + 60, T0 + 60)  # the next start after a crash
    assert lost_span(note) is None  # once


def make_reader(store, tracker, reads, clock, **kwargs):
    calls = {"live": 0, "kept": 0}

    def live(image):
        calls["live"] += 1
        return reads[id(image)]

    def kept(image, mode):
        calls["kept"] += 1
        return reads[id(image)]

    reader = ChatReader(live, store, tracker, clock=lambda: clock[0], min_gap_s=0.0,
                        read_kept=kept, **kwargs)  # fmt: skip
    return reader, calls


def test_a_deferred_match_reads_nothing_until_it_ends_then_the_same_lines_as_live(store, caplog):
    shots = replay()
    reads = {id(image): lines for _, image, lines in shots}

    live_tracker = MatchTracker(store, Pause())
    live_tracker.capture_alive(T0)
    live_tracker.new_match(T0, source="heroselect", mode="QUICK PLAY", map_name="Esperança")
    live_reader, _ = make_reader(store, live_tracker, reads, [T0])
    for t, image, _ in shots:
        live_reader.read_frame(t, image)
    expected = stored(store, live_tracker.match_id)
    assert len(expected) == 14

    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0 + 1000)
    tracker.new_match(T0 + 1000, source="heroselect", mode="COMPETITIVE", map_name="Busan")
    comp = tracker.match_id
    clock, deferring, heard = [T0], [True], []
    reader, calls = make_reader(
        store, tracker, reads, clock, deferring=lambda: deferring[0],
        on_player=lambda player, match, after: heard.append(after),
    )  # fmt: skip
    reader.start()
    try:
        for t, image, _ in shots:
            clock[0] = t
            reader.offer(image, "after")
        time.sleep(0.1)
        assert calls == {"live": 0, "kept": 0}  # not one OCR call during the match
        assert len(reader.later) == len(shots)
        tracker.end_match(T0 + 1300, outcome="victory")
        tracker.new_match(T0 + 1400, source="heroselect", mode="QUICK PLAY", map_name="Ilios")
        deferring[0] = False
        with caplog.at_level(logging.INFO, logger="yaptracker.reader"):
            wait_for(lambda: reader.read_frames == len(shots))
    finally:
        reader.stop()
    assert calls == {"live": 0, "kept": len(shots)}
    # real timestamps, in order, into the match they were seen in, not the one running now
    assert stored(store, comp) == expected
    assert stored(store, tracker.match_id) == []
    assert heard and all(heard)  # their cards say "Look who was there!"
    assert f"read {len(shots)} kept chat frames" in caplog.text


def test_frames_wait_behind_kept_ones_so_everything_is_read_in_order(store):
    a, b = frame(), frame()
    reads = {id(a): [OcrLine("[Pip]: gg", 0.99, Region(64, 10, 400, 24))],
             id(b): [OcrLine("[Pip]: gg", 0.99, Region(64, 10, 400, 24)),
                     OcrLine("[Pip]: wp", 0.99, Region(64, 40, 400, 24))]}  # fmt: skip
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    tracker.new_match(T0, source="heroselect", mode="COMPETITIVE", map_name="Busan")
    clock = [T0 + 5]
    reader, calls = make_reader(store, tracker, reads, clock)
    reader.offer(a, "after")
    clock[0] = T0 + 6
    reader.offer(b, "best")  # the match is over, but a kept frame is still unread
    assert reader._pending is None and len(reader.later) == 2
    reader.read_frame(*_kept(reader))
    reader.read_frame(*_kept(reader))
    assert [m.text for m in store.messages(tracker.match_id)] == ["gg", "wp"]


def _kept(reader):
    kept = reader.later.pop()
    return kept.ts, kept.image, kept


def test_quitting_with_frames_unread_leaves_a_gap_record(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    clock = [T0 + 10]
    reader, _ = make_reader(store, tracker, {}, clock, deferring=lambda: True)
    reader.start()
    reader.offer(frame(), "after")
    clock[0] = T0 + 70
    reader.offer(frame(), "after")
    reader.stop()
    assert store.all_gaps() == [(T0 + 10, T0 + 70, "deferred_lost")]


def test_faces_heard_after_the_match_say_so(store):
    pid = store.add_player("Pip", T0 - 5000)
    old = store.start_match(store.start_session(T0 - 5000), T0 - 5000, "heroselect")
    store.add_message(ts=T0 - 4990, match_id=old, channel="match", text="hi", player_id=pid)
    faces = FamiliarFaces(store, clock=lambda: T0)
    card = faces.heard(pid, old + 1, after=True)
    assert card is not None and card.after


def test_reading_waits_while_deferring_and_starts_by_itself_once_idle(store):
    image = frame()
    reads = {id(image): [OcrLine("[Pip]: hello", 0.99, Region(64, 10, 400, 24))]}
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    tracker.new_match(T0, source="heroselect", mode="COMPETITIVE", map_name="Busan")
    deferring = threading.Event()
    deferring.set()
    reader, calls = make_reader(store, tracker, reads, [T0 + 3],
                                deferring=deferring.is_set)  # fmt: skip
    reader.start()
    try:
        reader.offer(image, "after")
        time.sleep(0.1)
        assert calls["kept"] == 0
        deferring.clear()  # the reader looks again within LATER_POLL_S
        wait_for(lambda: calls["kept"] == 1, timeout=5)
    finally:
        reader.stop()
    assert [m.text for m in store.messages(tracker.match_id)] == ["hello"]

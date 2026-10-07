"""Tidy up light readings (#336): a light match's frames read again with the best quality when
idle; better readings replace light ones, missed lines go in at their real time."""

import json
import logging
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from yaptracker.capture.source import Region
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


def light(lines):
    """Windows OCR, roughly: misses mossyfox's "gg" and garbles "Enemy"."""
    return [OcrLine(o.text.replace("Enemy", "Enemv"), o.confidence, o.box)
            for o in lines if "mossyfox" not in o.text]  # fmt: skip


def replay():
    shots = []
    for f in json.loads(REPLAY.read_text(encoding="utf-8"))["frames"]:
        lines = [OcrLine(o["text"], o["confidence"], Region(*o["box"])) for o in f["ocr"]]
        shots.append((T0 + f["t"], np.zeros((395, 615, 3), np.uint8), lines))
    return shots


def stored(store, match_id):
    return [(m.ts, m.speaker_raw, m.text) for m in store.messages(match_id)]


def match(store, mode="COMPETITIVE"):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(T0)
    tracker.new_match(T0, source="heroselect", mode=mode, map_name="Esperança")
    return tracker


def reader_for(store, tracker, best, clock, **kwargs):
    """best: the best engine's reading of each image, by id(); light() reads it worse."""
    return ChatReader(lambda image: light(best[id(image)]), store, tracker,
                      clock=lambda: clock[0], min_gap_s=0.0,
                      read_kept=lambda image, mode: best[id(image)], **kwargs)  # fmt: skip


def test_the_tidy_up_ends_with_the_best_readings_and_the_missed_lines(store, caplog):
    shots = replay()
    best = {id(image): lines for _, image, lines in shots}
    best_tracker = match(store)
    best_reader = ChatReader(lambda image: best[id(image)], store, best_tracker)
    for t, image, _ in shots:
        best_reader.read_frame(t, image)
    expected = stored(store, best_tracker.match_id)

    tracker, clock = match(store), [T0]
    reader = reader_for(store, tracker, best, clock)
    for t, image, _ in shots:
        clock[0] = t
        reader.read_frame(t, image)  # live, light
        reader.keep_for_tidy(image)
    light_lines = stored(store, tracker.match_id)
    assert not any(speaker == "mossyfox" for _, speaker, _ in light_lines)
    assert ("MaybeMaybe", "Enemv Tracer!") in [(who, text) for _, who, text in light_lines]
    with caplog.at_level(logging.INFO, logger="yaptracker.reader"):
        while (kept := reader.tidy_frames.pop()) is not None:
            reader.tidy_frame(kept)
    assert stored(store, tracker.match_id) == expected
    assert f"tidied match {tracker.match_id}: 1 fixed, 1 found" in caplog.text
    assert reader.tidied == (tracker.match_id, 1, 1)


def line(text, y):
    return OcrLine(text, 0.99, Region(64, y, 400, 24))


def test_lines_fixed_or_deleted_by_hand_stay_as_they_are(store):
    image = np.zeros((100, 400, 3), np.uint8)
    best = {id(image): [line("[Pip]: Oops", 10), line("[Pip]: hello", 40)]}
    tracker, clock = match(store), [T0 + 5]
    reader = reader_for(store, tracker, best, clock)
    reader.read_frame(T0 + 5, image)
    oops, hello = store.messages(tracker.match_id)
    store.edit_message(oops.id, "Oops!!", T0 + 60)  # fixed by hand
    store.delete_message(hello.id, T0 + 60)
    reader.keep_for_tidy(image)
    reader.tidy_frame(reader.tidy_frames.pop())
    assert [m.text for m in store.messages(tracker.match_id)] == ["Oops!!"]  # hello stays gone
    assert reader.tidied == (tracker.match_id, 0, 0)


def test_the_tidy_up_waits_for_idle_and_pauses_when_a_match_starts(store):
    a, b = np.zeros((100, 400, 3), np.uint8), np.zeros((100, 400, 3), np.uint8)
    best = {id(a): [line("[Pip]: hi", 10)],
            id(b): [line("[Pip]: hi", 10), line("[Pip]: bye", 40)]}  # fmt: skip
    tracker, clock = match(store), [T0 + 5]
    idle = threading.Event()
    reader = reader_for(store, tracker, best, clock, idle=idle.is_set)
    reader.read_frame(T0 + 5, a)
    reader.keep_for_tidy(a)
    clock[0] = T0 + 8
    reader.keep_for_tidy(b)  # light never saw "bye"
    reader.start()
    try:
        time.sleep(0.1)
        assert len(reader.tidy_frames) == 2  # a match runs: hands off
        idle.set()
        _wait(lambda: reader.tidied is not None)
    finally:
        reader.stop()
    assert [(m.ts, m.text) for m in store.messages(tracker.match_id)] == [
        (T0 + 5, "hi"),
        (T0 + 8, "bye"),  # at its real time
    ]


def _wait(done, timeout=10.0):
    end = time.monotonic() + timeout
    while not done():
        assert time.monotonic() < end, "the reader didn't get there in time"
        time.sleep(0.01)

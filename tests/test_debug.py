"""Debug samples (#63, #110): what is kept, when, and that it never grows past its limits."""

import json
import time

import numpy as np
import pytest

from yaptracker import config
from yaptracker.debug import DebugSamples
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.store.repo import Store

NOON = time.mktime((2026, 10, 1, 12, 0, 0, 0, 0, -1))


class Clock:
    def __init__(self, now=NOON):
        self.now = now

    def __call__(self):
        return self.now


def signals(overview=True):
    crops = {"end_banner": np.full((25, 82, 3), 200, np.uint8)}
    if overview:
        crops["overview"] = np.zeros((36, 64, 3), np.uint8)
    return crops


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def samples(tmp_path, clock):
    return DebugSamples(tmp_path / "debug", lambda: True, clock)


def files(folder):
    return sorted(p.name for p in folder.iterdir())


def test_a_match_end_keeps_the_newest_overview_and_what_the_detectors_read(samples, clock):
    for _ in range(3):
        samples.on_signals(signals())
        clock.now += 5
    sample = samples.match_event("end")
    assert sample.parent.name == "2026-10-01" and sample.name == "12-00-15-end"
    assert files(sample) == ["12-00-10.jpg", "end_banner.png"]


def test_a_missed_end_keeps_the_last_six_minutes(samples, clock):
    for _ in range(100):  # 500 s of overviews, one every 5 s
        samples.on_signals(signals())
        clock.now += 5
    sample = samples.match_event("missed-end")
    assert len([f for f in files(sample) if f.endswith(".jpg")]) == 73  # 360 s / 5 s, both ends


def test_nothing_is_kept_while_paused_or_switched_off(tmp_path, samples, clock):
    samples.on_signals(signals())
    samples.on_signals(signals(), paused=True)  # pausing forgets what was buffered, too
    assert samples.match_event("start") is None
    off = DebugSamples(tmp_path / "off", lambda: False, clock)
    off.on_signals(signals())
    assert off.match_event("start") is None and not (tmp_path / "off").exists()


def test_old_days_and_the_oldest_samples_go_first(tmp_path, clock):
    folder = tmp_path / "debug"
    existing = [
        ("2026-09-01", "20-00-00-end", 10),
        ("2026-09-30", "20-00-00-end", 600),
        ("2026-09-30", "21-00-00-end", 600),
        ("2026-10-01", "11-00-00-end", 600),
    ]
    for day, name, size in existing:
        (folder / day / name).mkdir(parents=True)
        (folder / day / name / "x.jpg").write_bytes(b"x" * size)
    DebugSamples(folder, lambda: True, clock, cap_bytes=1300).start(background=False)
    assert files(folder) == ["2026-09-30", "2026-10-01"]  # 30 days old: gone
    assert files(folder / "2026-09-30") == ["21-00-00-end"]  # oldest went to fit 1300 bytes


def test_on_by_default_only_in_pre_releases(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "__version__", "0.2.80")
    assert config.debug_samples(path)
    monkeypatch.setattr(config, "__version__", "1.0.0")
    assert not config.debug_samples(path)
    config.save_debug_samples(True, path)
    assert config.debug_samples(path)


def test_a_start_without_an_end_screen_counts_as_a_missed_end(tmp_path):
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    missed = []
    tracker = MatchTracker(store, Pause(), on_missed_end=lambda: missed.append(True))
    tracker.capture_alive(1000.0)
    tracker.new_match(1000.0, source="heroselect")
    tracker.end_match(1600.0, outcome="victory")
    tracker.new_match(1700.0, source="heroselect")  # the end screen was seen: fine
    assert missed == []
    tracker.new_match(2400.0, source="heroselect")  # no end screen in between
    tracker.new_match(2500.0)  # Ctrl+Alt+M is the user's call, not a miss
    assert missed == [True]
    store.close()


def chat_frame(text="[NoodleBonk]: gg", confidence=0.99, kind="message", channel="match"):
    """(image, ocr, parsed lines, new yaps) as the chat reader hands them over (#110)."""
    from yaptracker.capture.source import Region
    from yaptracker.dedup import Yap
    from yaptracker.ocr.engine import OcrLine
    from yaptracker.parser import ChatLine

    box = Region(64, 10, 300, 24)
    line = ChatLine(kind, channel, text, confidence, box, speaker="NoodleBonk")
    yap = Yap(1, 0.0)
    yap.add(line)
    image = np.full((395, 615, 3), 40, np.uint8)
    return image, [OcrLine(text, confidence, box)], [line], [yap] if kind == "message" else []


def test_a_shaky_chat_line_saves_the_last_20_seconds_of_chat(samples, clock):
    for t in range(0, 40, 2):  # 40 s of fine chat ...
        clock.now = NOON + t
        assert samples.chat_read(clock.now, *chat_frame()) is None
    clock.now = NOON + 40
    sample = samples.chat_read(clock.now, *chat_frame("[NoodleBonk]: g9", confidence=0.6))
    assert sample.name == "12-00-40-chat"
    frames = json.loads((sample / "sample.json").read_text(encoding="utf-8"))
    assert frames["why"] == "low-confidence"
    assert len(frames["frames"]) == 11  # 20 s back, every 2 s
    assert frames["frames"][-1]["parsed"][0]["text"] == "[NoodleBonk]: g9"
    assert files(sample)[-2].endswith(".png")  # the hard frame lossless, context as JPEG


def test_hard_chat_is_sampled_once_a_minute_and_map_text_never(samples, clock):
    assert samples.chat_read(clock.now, *chat_frame("PORTUGAL", kind="unknown")) is None
    assert samples.chat_read(clock.now, *chat_frame("[x]: ok", channel="unknown")) is not None
    clock.now += 30
    assert samples.chat_read(clock.now, *chat_frame("[x]: ok", channel="unknown")) is None
    clock.now += 31
    sample = samples.chat_read(clock.now, *chat_frame("Name (Ana) hi", kind="unknown"))
    assert json.loads((sample / "sample.json").read_text(encoding="utf-8"))["why"] == "unparsed"


def test_the_hotkey_saves_on_purpose_and_a_pause_forgets(samples, clock):
    samples.chat_read(clock.now, *chat_frame())
    assert samples.save_chat().name.endswith("-chat")  # Ctrl+Alt+S, nothing hard needed
    samples.on_signals({}, paused=True)
    assert samples.save_chat() is None

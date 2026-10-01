"""Debug samples (#63): what is kept, when, and that it never grows past its limits."""

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
    DebugSamples(folder, lambda: True, clock, cap_bytes=1300).clean_up()
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

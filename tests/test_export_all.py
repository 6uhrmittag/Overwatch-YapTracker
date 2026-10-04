"""Export everything (#69): one documented JSON file, checked against its published schema."""

import json
import random
import time
from pathlib import Path

import jsonschema
import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, paths, runtime
from yaptracker.export import export_all
from yaptracker.store.repo import Store
from yaptracker.ui import shell

SCHEMA = json.loads((Path(__file__).parents[1] / "docs" / "export.schema.json").read_text())
EVENING = time.mktime((2026, 10, 1, 20, 0, 0, 0, 0, -1))


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def evening(store):
    """Two matches, the second with a capture gap; one spicy line, one line outside a match."""
    session = store.start_session(EVENING)
    noodle = store.add_player("NoodleBonk", EVENING)
    store.set_verdict(noodle, "friend")
    store.add_alias(noodle, "NoodIeBonk")
    first = store.start_match(session, EVENING + 60, "heroselect", "UNRANKED", "ESPERANÇA")
    store.add_message(ts=EVENING + 90, channel="match", text="gl hf ◇", speaker_raw="NoodleBonk",
                      player_id=noodle, match_id=first, ocr_confidence=0.97,
                      has_glyphs=True)  # fmt: skip
    store.add_message(ts=EVENING + 95, channel="team", text="Group up!", speaker_raw="Marv",
                      hero="Lúcio", role="me", match_id=first)  # fmt: skip
    store.end_match(first, EVENING + 700, "victory")
    second = store.start_match(session, EVENING + 800, "endscreen")
    store.add_message(ts=EVENING + 820, channel="match", text="ez", speaker_raw="gremlin.exe",
                      match_id=second, flagged="overwatch")  # fmt: skip
    gap = store.open_gap(EVENING + 900, "no_frames")
    store.close_gap(gap, EVENING + 960)
    store.end_match(second, EVENING + 1100, "defeat")
    store.add_message(ts=EVENING + 1000, channel="system", text="You left the group.")
    store.end_session(session, EVENING + 1200)
    return noodle, first, second


def test_everything_is_in_it_and_it_matches_the_schema(store, tmp_path):
    noodle, first, second = evening(store)
    seen = []
    path = export_all(store, tmp_path / "out", EVENING + 2000, lambda d, t: seen.append((d, t)))
    data = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.validate(data, SCHEMA)
    assert (data["format"], data["format_version"], data["anonymized"]) == (
        "yaptracker-export", 1, False,
    )  # fmt: skip
    (session,) = data["sessions"]
    one, two = session["matches"]
    assert (one["number"], one["map"], one["detected_by"], one["outcome"]) == (
        1, "ESPERANÇA", "heroselect", "victory",
    )  # fmt: skip
    assert [m["text"] for m in one["messages"]] == ["gl hf ◇", "Group up!"]
    assert one["messages"][0]["player_id"] == noodle and one["messages"][0]["has_glyphs"]
    assert (one["messages"][1]["role"], one["messages"][1]["hero"]) == ("me", "Lúcio")
    assert (one["incomplete"], two["incomplete"]) == (False, True)  # the gap was in match 2
    assert two["messages"][0]["flagged"] == "overwatch"  # spicy (#77)
    assert [m["text"] for m in data["messages_outside_matches"]] == ["You left the group."]
    assert data["players"][0]["aliases"] == ["NoodIeBonk"]
    assert data["capture_gaps"][0]["reason"] == "no_frames"
    assert one["started_at"].startswith("2026-10-01T20:01:00")
    assert seen[-1] == (4, 4)
    assert not list((tmp_path / "out").glob("*.tmp"))


def test_empty_database_is_a_valid_export_too(store, tmp_path):
    data = json.loads(export_all(store, tmp_path, EVENING).read_text(encoding="utf-8"))
    jsonschema.validate(data, SCHEMA)
    assert data["sessions"] == [] and data["players"] == []


def test_capture_keeps_writing_while_100k_messages_export(store, tmp_path):
    random.seed(69)
    session = store.start_session(EVENING)
    matches = [store.start_match(session, EVENING + n * 600, "gap") for n in range(1000)]
    rows = [(matches[n // 100], EVENING + n * 6, "team", f"player{n % 997}", "gg " * (n % 7 + 1))
            for n in range(100_000)]  # fmt: skip
    store._conn.execute("BEGIN")
    store._conn.executemany(
        "INSERT INTO chat_messages (match_id, ts, channel, speaker_raw, text) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    store._conn.execute("COMMIT")
    wrote = []

    def progress(done, total):
        if done == 50_000:  # halfway: the capture thread writes a new line meanwhile
            wrote.append(store.add_message(ts=EVENING, channel="match", text="still here"))

    path = export_all(store, tmp_path, EVENING, progress)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert sum(len(m["messages"]) for m in data["sessions"][0]["matches"]) == 100_000
    assert wrote  # no time limit: a slow runner must not turn CI red (#310)


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_export_everything_from_settings(user: User, store, monkeypatch, tmp_path):
    config.save_setup_state("done")
    evening(store)
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(paths, "export_dir", lambda: tmp_path / "Documents" / "YapTracker")
    await user.open("/")
    user.find(marker="nav-settings").click()
    user.find(marker="export-all").click()
    await user.should_see("yaptracker-export.json", retries=50)
    (path,) = (tmp_path / "Documents" / "YapTracker").glob("export-*/yaptracker-export.json")
    jsonschema.validate(json.loads(path.read_text(encoding="utf-8")), SCHEMA)

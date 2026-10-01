"""Export everything (#158): Markdown next to the JSON, anonymized names, line pictures."""

import json
import re
import time
from pathlib import Path

import jsonschema
import numpy as np
import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, paths, runtime
from yaptracker.capture.source import Region
from yaptracker.export import _md, export_all
from yaptracker.lines import LinePictures
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
    session = store.start_session(EVENING)
    noodle = store.add_player("NoodleBonk", EVENING)
    store.add_alias(noodle, "NoodIeBonk")
    store.set_notes(noodle, "Hype Lucio. Lives in Berlin.")
    match = store.start_match(session, EVENING + 60, "heroselect", "UNRANKED", "ESPERANCA")
    lines = [
        ("system", "gremlin.exe", None, "[gremlin.exe] started playing Overwatch."),
        ("match", "NoodleBonk", noodle, "gl hf *wahoo* <3"),
        ("match", "NoodIeBonk", noodle, "again"),  # a misread spelling, same yapper
        ("team", "Marv", None, "gremlin.exe pls swap, NoodleBonk is free"),
        ("match", "gremlin.exe", None, "ez"),
    ]
    ids = [store.add_message(ts=EVENING + 90 + n * 10, channel=ch, text=text, speaker_raw=who,
                             player_id=pid, match_id=match, role="me" if who == "Marv" else None)
           for n, (ch, who, pid, text) in enumerate(lines)]  # fmt: skip
    store.set_flag(ids[-1], "manual")
    gap = store.open_gap(EVENING + 200, "no_frames")
    store.close_gap(gap, EVENING + 260)
    store.end_match(match, EVENING + 400, "defeat")
    store.end_session(session, EVENING + 500)
    return ids


def test_markdown_files_read_like_the_transcript(store, tmp_path):
    evening(store)
    export_all(store, tmp_path, EVENING + 600, markdown=True)
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "- 1 session, 1 match, 5 yaps, 1 yapper" in readme
    assert "- From 2026-10-01 to 2026-10-01" in readme
    (day,) = (tmp_path / "sessions").iterdir()
    text = day.read_text(encoding="utf-8")
    assert text.startswith("# Thursday, Oct 1, 2026\n")
    assert "## Match 1 on Esperanca · Unranked · lost" in text
    assert "- 20:01 · Match · **NoodleBonk:** gl hf \\*wahoo\\* \\<3" in text
    assert "**you:** gremlin.exe pls swap" in text  # own line
    assert text.index("Not recorded 20:03–20:04") > text.index("**you:**")  # at its place
    assert "Hype Lucio" in (tmp_path / "players.md").read_text(encoding="utf-8")


def test_anonymized_everywhere_consistent_notes_out_flags_kept(store, tmp_path):
    evening(store)
    path = export_all(store, tmp_path, EVENING + 600, markdown=True, anonymize=True)
    data = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.validate(data, SCHEMA)
    assert data["anonymized"] is True
    everything = path.read_text(encoding="utf-8") + "".join(
        f.read_text(encoding="utf-8") for f in tmp_path.rglob("*.md")
    )
    for real in ("NoodleBonk", "NoodIeBonk", "gremlin.exe", "Marv", "Berlin"):
        assert real not in everything, real
    said = data["sessions"][0]["matches"][0]["messages"]
    noodle = said[1]["speaker"]
    assert re.fullmatch(r"Player-[0-9a-f]{4}", noodle)
    assert said[2]["speaker"] == noodle  # the misread spelling is the same pseudonym
    assert said[0]["text"] == f"[{said[4]['speaker']}] started playing Overwatch."
    assert said[3]["text"] == f"{said[4]['speaker']} pls swap, {noodle} is free"
    assert said[4]["flagged"] == "manual"  # spicy stays (#77)
    (player,) = data["players"]
    assert (player["display_name"], player["notes"], player["aliases"]) == (noodle, "", [])


def test_two_anonymized_exports_use_different_pseudonyms(store, tmp_path):
    evening(store)
    one = json.loads(export_all(store, tmp_path / "a", EVENING, anonymize=True).read_text())
    two = json.loads(export_all(store, tmp_path / "b", EVENING, anonymize=True).read_text())
    assert one["players"][0]["display_name"] != two["players"][0]["display_name"]


def test_line_pictures_ride_along_but_never_when_anonymized(store, tmp_path):
    ids = evening(store)
    pictures = LinePictures(tmp_path / "lines")
    frame = np.full((40, 200, 3), 30, dtype=np.uint8)
    pictures.save(ids[1], EVENING + 100, frame, Region(0, 0, 200, 20))
    path = export_all(store, tmp_path / "out", EVENING, pictures=pictures)
    said = json.loads(path.read_text())["sessions"][0]["matches"][0]["messages"]
    assert said[1]["picture"] == f"line-images/{ids[1]}.webp"
    assert (tmp_path / "out" / said[1]["picture"]).exists()
    assert "picture" not in said[0]  # no picture kept for that line
    anon = export_all(store, tmp_path / "anon", EVENING, anonymize=True, pictures=pictures)
    assert "picture" not in anon.read_text() and not (tmp_path / "anon" / "line-images").exists()


def test_markdown_escaping():
    assert _md("# not a heading [link](x) **bold** <b>") == (
        "\\# not a heading \\[link\\](x) \\*\\*bold\\*\\* \\<b\\>"
    )


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_anonymized_export_from_settings(user: User, store, monkeypatch, tmp_path):
    config.save_setup_state("done")
    evening(store)
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(paths, "export_dir", lambda: tmp_path / "Documents" / "YapTracker")
    await user.open("/")
    user.find(marker="nav-settings").click()
    user.find(marker="export-anonymize").click()
    user.find(marker="export-all").click()
    await user.should_see("yaptracker-export.json", retries=50)
    (folder,) = (tmp_path / "Documents" / "YapTracker").glob("export-*-anonymized")
    assert (folder / "README.md").exists()  # Markdown is on by default
    assert "NoodleBonk" not in (folder / "yaptracker-export.json").read_text(encoding="utf-8")

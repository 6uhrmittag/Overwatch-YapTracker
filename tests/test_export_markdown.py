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
    assert "- 1 day, 1 match, 5 yaps, 1 yapper" in readme
    assert "- From 2026-10-01 to 2026-10-01" in readme
    (day,) = (tmp_path / "days").iterdir()
    assert day.name == "2026-10-01.md"
    text = day.read_text(encoding="utf-8")
    assert text.startswith("# Thursday, Oct 1, 2026\n\n20:01–20:06 · 5 min played · 1 match")
    assert "## Match 1 on Esperanca · Unranked · lost" in text
    assert "- 20:01 · Match · **NoodleBonk:** gl hf \\*wahoo\\* \\<3" in text
    assert "**you:** gremlin.exe pls swap" in text  # own line
    assert text.index("Not recorded 20:03–20:04") > text.index("**you:**")  # at its place
    assert "Hype Lucio" in (tmp_path / "players.md").read_text(encoding="utf-8")


def test_one_markdown_file_per_day_like_sessions(store, tmp_path):
    """#443: two sessions and a late match past midnight are one day: one file, matches
    numbered 1..N, a break line between play blocks. The JSON keeps its sessions."""

    def played(session, start, map_name):
        match = store.start_match(session, start, "heroselect", "UNRANKED", map_name)
        store.add_message(ts=start + 60, channel="match", text="gg", match_id=match)
        store.end_match(match, start + 600, "victory")

    afternoon = store.start_session(EVENING - 4 * 3600)  # 16:00
    played(afternoon, EVENING - 4 * 3600 + 60, "KING'S ROW")
    store.end_session(afternoon, EVENING - 4 * 3600 + 700)
    late = store.start_session(EVENING + 3 * 3600)  # 23:00, until after midnight
    played(late, EVENING + 3 * 3600 + 60, "NEPAL")
    played(late, EVENING + 4 * 3600 + 60, "BUSAN")  # 00:01, still Thursday
    store.end_session(late, EVENING + 4 * 3600 + 700)
    path = export_all(store, tmp_path, EVENING + 5 * 3600, markdown=True)
    (day,) = (tmp_path / "days").iterdir()
    text = day.read_text(encoding="utf-8")
    titles = [line for line in text.splitlines() if line.startswith(("## ", "*Break"))]
    assert titles == ["## Match 1 on King's Row · Unranked · won", "*Break, 6 h 50 min*",
                      "## Match 2 on Nepal · Unranked · won", "*Break, 50 min*",
                      "## Match 3 on Busan · Unranked · won"]  # fmt: skip
    assert "16:01–00:11 · 30 min played · 3 matches · 3 yaps" in text
    assert len(json.loads(path.read_text(encoding="utf-8"))["sessions"]) == 2
    assert "- 1 day, 3 matches" in (tmp_path / "README.md").read_text(encoding="utf-8")


def test_days_come_out_right_whatever_order_sessions_were_stored_in(store, tmp_path):
    """#443 review: a clock corrected mid-week stores a session out of time order. Day files
    are grouped like the Sessions tab, never overwritten; README and JSON say the same."""

    def played(start, map_name):
        session = store.start_session(start)
        match = store.start_match(session, start + 60, "heroselect", "UNRANKED", map_name)
        store.add_message(ts=start + 90, channel="match", text="gg", match_id=match)
        store.end_match(match, start + 600, "victory")
        store.end_session(session, start + 700)

    played(EVENING, "Ilios")  # Thursday 20:00
    played(EVENING + 2 * 86400, "Throne of Anubis")  # Saturday
    played(EVENING + 2 * 3600, "Hanaoka")  # Thursday 22:00, stored last
    path = export_all(store, tmp_path, EVENING + 3 * 86400, markdown=True)
    files = sorted(p.name for p in (tmp_path / "days").iterdir())
    assert files == ["2026-10-01.md", "2026-10-03.md"]
    thursday = (tmp_path / "days" / "2026-10-01.md").read_text(encoding="utf-8")
    assert "## Match 1 on Ilios" in thursday and "## Match 2 on Hanaoka" in thursday
    assert "## Match 1 on Throne of Anubis" in (tmp_path / "days" / "2026-10-03.md").read_text(
        encoding="utf-8"
    )  # as stored, not "Throne Of Anubis"
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "- 2 days, 3 matches" in readme and "- From 2026-10-01 to 2026-10-03" in readme
    data = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.validate(data, SCHEMA)
    days = [(m["map"], m["day"], m["day_number"]) for s in data["sessions"] for m in s["matches"]]
    assert days == [("Ilios", "2026-10-01", 1), ("Throne of Anubis", "2026-10-03", 1),
                    ("Hanaoka", "2026-10-01", 2)]  # fmt: skip


def test_a_new_export_into_the_same_folder_leaves_nothing_stale(store, tmp_path):
    evening(store)
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / "2026-10-01-session-1.md").write_text("old", encoding="utf-8")
    (tmp_path / "days").mkdir()
    (tmp_path / "days" / "2026-09-30.md").write_text("a day since merged away", encoding="utf-8")
    export_all(store, tmp_path, EVENING + 600, markdown=True)
    assert not (tmp_path / "sessions").exists()
    assert [p.name for p in (tmp_path / "days").iterdir()] == ["2026-10-01.md"]


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


async def test_one_switch_per_row_and_no_pictures_when_anonymized(user: User):
    """#397: every switch says right under it what it does; anonymizing switches the line
    pictures off and greys them out with the reason, since the pictures show the names."""
    config.save_setup_state("done")
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("Also writes the readable .md files next to the JSON")
    await user.should_see("Every name becomes Player-xxxx and your notes stay out. Safe to share.")
    (pictures,) = user.find(marker="export-pictures").elements
    user.find(marker="export-pictures").click()
    assert pictures.props["aria-checked"] == "true"
    user.find(marker="export-anonymize").click()
    assert pictures.props["aria-checked"] == "false" and "disabled" in pictures.props
    assert "show the names" in pictures.props["title"]
    user.find(marker="export-anonymize").click()
    assert "disabled" not in pictures.props

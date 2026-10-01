"""Export players and notes (#31): players.md for people, players.json for scripts."""

import json
import time

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, paths, runtime
from yaptracker.export import export_folder, export_players
from yaptracker.store.repo import Store
from yaptracker.ui import shell

NOW = time.mktime((2026, 10, 1, 22, 30, 0, 0, 0, -1))
MET = time.mktime((2026, 9, 29, 20, 5, 0, 0, 0, -1))


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    session = s.start_session(MET)
    noodle = s.add_player("NoodleBonk", MET)
    s.set_verdict(noodle, "friend")
    s.set_notes(noodle, "Hype Lucio. Greet with a wahoo.\nPlays EU evenings.")
    s.add_alias(noodle, "NoodIeBonk")
    for n in range(2):
        match = s.start_match(session, MET + n * 900, "heroselect")
        s.add_message(ts=MET + n * 900 + 60, channel="match", text="wahoo", match_id=match,
                      speaker_raw="NoodleBonk", player_id=noodle)  # fmt: skip
    s.player_seen(noodle, NOW - 3600)
    s.add_player("zappy", MET)  # met, never said a word, no verdict
    yield s
    s.close()


def test_json_has_everything_about_every_player(store, tmp_path):
    md, js = export_players(store, tmp_path / "out", NOW)
    data = json.loads(js.read_text(encoding="utf-8"))
    assert (data["format"], data["format_version"]) == ("yaptracker-players", 1)
    assert data["exported_at"].startswith("2026-10-01T22:30:00")
    noodle, zappy = data["players"]
    assert noodle == {
        "id": noodle["id"],
        "display_name": "NoodleBonk",
        "verdict": "friend",
        "notes": "Hype Lucio. Greet with a wahoo.\nPlays EU evenings.",
        "first_met": noodle["first_met"],
        "last_met": noodle["last_met"],
        "aliases": ["NoodIeBonk"],
        "matches": 2,
        "messages": 2,
        "callouts": 0,
        "flagged_messages": 0,
    }
    assert noodle["first_met"].startswith("2026-09-29T20:05:00")  # ISO 8601 with time zone
    assert noodle["last_met"][19] in "+-Z"
    assert (zappy["verdict"], zappy["notes"], zappy["aliases"]) == (None, "", [])


def test_markdown_one_section_per_player(store, tmp_path):
    md, _ = export_players(store, tmp_path / "out", NOW)
    text = md.read_text(encoding="utf-8")
    assert text.startswith("# Yappers\n\nExported 2026-10-01 22:30 from YapTracker")
    assert "2 yappers." in text
    noodle = text.split("## NoodleBonk\n")[1].split("## ")[0]
    assert "- Verdict: Bestie" in noodle
    assert "- Last met: 2026-10-01 (first: 2026-09-29)" in noodle
    assert "- 2 matches together, 2 yaps" in noodle
    assert "- Also read as: NoodIeBonk" in noodle
    assert "Hype Lucio. Greet with a wahoo.\nPlays EU evenings." in noodle
    zappy = text.split("## zappy\n")[1]
    assert "- Verdict: none yet" in zappy and "- 0 matches together, 0 yaps" in zappy


def test_one_folder_per_day_a_second_export_replaces_it(store, tmp_path):
    folder = export_folder(tmp_path, NOW)
    assert folder.name == "export-2026-10-01"
    export_players(store, folder, NOW)
    store.set_verdict(store.players()[1].id, "avoid")
    export_players(store, folder, NOW + 60)
    assert "- Verdict: Nope" in (folder / "players.md").read_text(encoding="utf-8")
    assert sorted(f.name for f in folder.iterdir()) == ["players.json", "players.md"]


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_export_from_settings(user: User, store, monkeypatch, tmp_path):
    config.save_setup_state("done")
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(paths, "export_dir", lambda: tmp_path / "Documents" / "YapTracker")
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("Export yappers")
    user.find(marker="export-players").click()
    await user.should_see("players.md, players.json")
    assert list((tmp_path / "Documents" / "YapTracker").glob("export-*/players.json"))

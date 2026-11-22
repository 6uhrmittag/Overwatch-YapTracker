"""Loved only (#286): Sessions narrowed to the hearted matches, and the export says which
they are up front without changing its documented order."""

import json
from pathlib import Path

import jsonschema
import pytest
from nicegui.testing import User, user_simulation

from tests.test_sessions import at, evening
from yaptracker import config, runtime
from yaptracker.export import export_all
from yaptracker.store.repo import Store
from yaptracker.ui import shell

SCHEMA = json.loads((Path(__file__).parents[1] / "docs" / "export.schema.json").read_text())
DAY = 24 * 60


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


def two_days(store) -> tuple[int, int, int]:
    """Thursday's two matches and one on Friday."""
    _, first, second = evening(store)
    session = store.start_session(at(DAY))
    third = store.start_match(session, at(DAY + 1), "heroselect", "unranked", "kings row")
    store.add_message(ts=at(DAY + 2), channel="match", text="hello", speaker_raw="zappy",
                      match_id=third)  # fmt: skip
    store.end_match(third, at(DAY + 9), "victory")
    store.end_session(session, at(DAY + 10))
    return first, second, third


async def open_sessions(user: User, store, monkeypatch) -> None:
    config.save_setup_state("done")
    monkeypatch.setattr(runtime, "store", store)
    await user.open("/")
    user.find(marker="nav-sessions").click()
    await user.should_see("Friday, Oct 2")


async def test_loved_only_shows_the_loved_days_and_matches_with_their_numbers(
    user: User, store, monkeypatch
):
    first, second, third = two_days(store)
    store.set_loved(second, at(30))
    await open_sessions(user, store, monkeypatch)
    user.find(marker="show-loved").click()
    await user.should_see("1 loved of 2 matches")
    await user.should_not_see("Friday, Oct 2")  # nothing loved that day
    user.find(marker="day").click()
    await user.should_see("Match 2")  # still the day's second match
    await user.should_not_see("Match 1 on Esperanca")
    assert len(user.find(marker="match").elements) == 1
    assert "is-active" in user.find(marker="show-loved").elements.pop().classes  # kept
    user.find(marker="show-all").click()
    await user.should_see("Match 1 on Esperanca")
    assert len(user.find(marker="match").elements) == 2


async def test_loved_only_says_in_words_when_there_is_nothing_to_show(
    user: User, store, monkeypatch
):
    first, second, third = two_days(store)
    await open_sessions(user, store, monkeypatch)
    user.find(marker="show-loved").click()
    await user.should_see("No loved matches yet")
    await user.should_see("Click the heart on a match")
    store.set_loved(first, at(30))
    user.find(marker="show-loved").click()
    user.find(marker="day").click()
    user.find(marker=f"match-{first}").click()
    await user.should_see("All matches")  # the transcript's way back
    user.find(marker="heart").click()  # taken back in the transcript
    user.find(marker="back-to-matches").click()
    await user.should_see("No loved match on this day")


def test_the_export_lists_the_loved_matches_up_front_and_keeps_its_order(store, tmp_path):
    first, second, third = two_days(store)
    store.set_loved(third, at(DAY + 20))
    store.set_loved(first, at(DAY + 30))  # loved later, played earlier
    path = export_all(store, tmp_path, at(2 * DAY), markdown=True)
    data = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.validate(data, SCHEMA)
    assert data["loved_matches"] == [first, third]  # play order, oldest first
    assert list(data).index("loved_matches") < list(data).index("sessions")
    played = [m["id"] for s in data["sessions"] for m in s["matches"]]
    assert played == [first, second, third]  # as documented: nothing moved
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    loved = readme[readme.index("## Loved matches") : readme.index("## What's inside")]
    assert loved.splitlines()[2:4] == [  # newest day first, like Sessions
        "- [Friday, Oct 2, 2026](days/2026-10-02.md): Match 1 on Kings Row",
        "- [Thursday, Oct 1, 2026](days/2026-10-01.md): Match 1 on Esperanca",
    ]
    assert (tmp_path / "days" / "2026-10-02.md").exists()


def test_an_export_without_a_heart_has_an_empty_list_and_no_heading(store, tmp_path):
    two_days(store)
    path = export_all(store, tmp_path, at(2 * DAY), markdown=True, anonymize=True)
    data = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.validate(data, SCHEMA)
    assert data["loved_matches"] == []
    assert "Loved matches" not in (tmp_path / "README.md").read_text(encoding="utf-8")

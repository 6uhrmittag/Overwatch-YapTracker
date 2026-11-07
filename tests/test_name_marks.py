"""A verdict mark next to known players' names (#519): in Live and transcripts, system lines too;
not for strangers, me or my crew. A click opens the familiar-face card (#518)."""

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, runtime
from yaptracker.identity import Identity
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.store.repo import Store
from yaptracker.ui import shell
from yaptracker.ui.name_marks import MET, NameMarks, system_name


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


def evening(store):
    """An earlier match with NoodleBonk (Bestie), Pebble and Void (crew); now a new one."""
    session = store.start_session(1.0)
    old = store.start_match(session, 10.0, "heroselect")
    ids = {}
    for name in ("NoodleBonk", "Pebble", "Void", "Kettle"):
        ids[name] = store.add_player(name, 10.0)
        if name != "Kettle":  # Kettle is new tonight
            store.add_message(ts=11.0, channel="match", text="hi", match_id=old,
                              speaker_raw=name, player_id=ids[name])  # fmt: skip
    store.set_verdict(ids["NoodleBonk"], "friend")
    tracker = MatchTracker(store, Pause())
    tracker.new_match(100.0, "heroselect")
    now = tracker.match_id
    lines = [("match", "NoodleBonk", "gg", None), ("team", "Pebble", "hello", None),
             ("team", "Kettle", "who dis", None), ("team", "Void", "on my way", "crew"),
             ("system", "NoodleBonk", "[NoodleBonk] started playing Overwatch.", None),
             ("system", None, "You endorsed Pebble!", None),
             ("system", None, "You have joined a group!", None)]  # fmt: skip
    for n, (channel, name, text, role) in enumerate(lines):
        pid = ids.get(name) if channel != "system" else None
        store.add_message(ts=101.0 + n, channel=channel, text=text, match_id=now, role=role,
                          speaker_raw=name, player_id=pid)  # fmt: skip
    return tracker, now, ids


MARKED = ["gg", "hello", "[NoodleBonk] started playing Overwatch.", "You endorsed Pebble!"]


def test_who_gets_which_mark(store, monkeypatch):
    monkeypatch.setattr(runtime, "store", store)
    _, now, ids = evening(store)
    messages = store.messages(now)
    marks = NameMarks(now, messages, Identity(crew=("Void",)))
    got = [marks.kind(marks.player(m)) for m in messages]
    assert got == ["friend", MET, None, None, "friend", MET, None]
    assert system_name(messages[5]) == ("Pebble", True)  # at the end of its line


def marked(user: User) -> list[str]:
    """The texts of the lines that show a mark, sorted."""
    lines = []
    for line in user.find(marker="chat-line").elements:
        marks = [e for e in line.descendants() if "name-mark" in e._markers and e.visible]
        if marks:
            lines.append(next(e.content for e in line.descendants() if "yt-line-text" in e.classes))
    return sorted(lines)


async def test_live_marks_known_names_and_a_click_shows_the_card(user: User, store, monkeypatch):
    config.save_setup_state("done")
    config.save_identity([], ["Void"])
    tracker, _, _ = evening(store)
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "matches", tracker)
    await user.open("/")
    await user.should_see("who dis")
    assert marked(user) == sorted(MARKED)
    first = store.messages(tracker.match_id)[0].id  # NoodleBonk's "gg"
    user.find(marker=f"name-mark-{first}").click()
    await user.should_see("Open profile")
    await user.should_see("1 match together")


async def test_a_transcript_marks_them_too(user: User, store, monkeypatch):
    config.save_setup_state("done")
    config.save_identity([], ["Void"])
    _, now, _ = evening(store)
    monkeypatch.setattr(runtime, "store", store)
    await user.open("/")
    user.find(marker="nav-sessions").click()
    user.find(marker="day").click()
    user.find(marker=f"match-{now}").click()
    await user.should_see("who dis")
    assert marked(user) == sorted(MARKED)

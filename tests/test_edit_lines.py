"""Fix a misread chat line in place (#227): Enter saves, Esc cancels, "edited" mark, the OCR
reading kept, search follows, a better reading doesn't undo it, and it becomes a sample."""

import json
import time

import pytest
from nicegui.testing import User, user_simulation
from nicegui.testing.user_interaction import UserInteraction

from yaptracker import config, runtime
from yaptracker.debug import DebugSamples
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.store.repo import Store
from yaptracker.ui import shell

NOW = time.time()


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


def test_an_edit_keeps_the_reading_and_search_follows_it(store):
    mid = store.add_message(ts=NOW, channel="match", speaker_raw="Pickle", text="glhf <з")
    store.edit_message(mid, "glhf <3", NOW + 5)
    fixed = store.message(mid)
    assert (fixed.text, fixed.original_text) == ("glhf <3", "glhf <з")
    store.update_message(mid, channel="match", speaker_raw="Pickle", text="glhf <з")  # re-read
    assert store.message(mid).text == "glhf <3"  # your fix wins over a later reading
    store.edit_message(mid, "glhf <33", NOW + 9)
    assert store.message(mid).original_text == "glhf <з"  # still the first OCR reading
    store.unedit_message(mid, "glhf <3", NOW + 5)
    assert (store.message(mid).text, store.message(mid).edited_at) == ("glhf <3", NOW + 5)
    store.unedit_message(mid, "glhf <з", None)
    assert (store.message(mid).original_text, store.message(mid).edited_at) == (None, None)


def test_search_finds_the_fixed_words_not_the_misread_ones(store):
    mid = store.add_message(ts=NOW, channel="match", speaker_raw="Pickle", text="nice shct")
    store.edit_message(mid, "nice shot", NOW)
    assert [m.id for m in store.search("shot")] == [mid]
    assert store.search("shct") == []


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_edit_in_live_saves_marks_and_keeps_a_sample(user: User, store, monkeypatch,
                                                          tmp_path):  # fmt: skip
    config.save_setup_state("done")
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(NOW)
    tracker.new_match()
    mid = store.add_message(ts=NOW, channel="match", speaker_raw="Pickle", text="drop the lanp",
                            match_id=tracker.match_id)  # fmt: skip
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "matches", tracker)
    monkeypatch.setattr(runtime, "debug", DebugSamples(tmp_path / "debug", lambda: True))
    await user.open("/")
    await user.should_see("drop the lanp")
    user.find(marker="edit-line").click()
    field = user.find(marker="edit-field")
    field.clear().type("drop the lamp")
    field.trigger("keydown.escape")  # Esc: nothing changes
    assert store.message(mid).text == "drop the lanp"
    user.find(marker="edit-line").click()
    field = user.find(marker="edit-field")
    field.clear().type("drop the lamp")
    field.trigger("keydown.enter")
    assert store.message(mid).text == "drop the lamp"
    await user.should_see("Line fixed")
    (sample,) = (tmp_path / "debug" / "corrections").glob("*.json")
    assert json.loads(sample.read_text(encoding="utf-8"))["ocr"] == "drop the lanp"
    assert [e for e in user.find(marker="edited-mark").elements if "yt-hidden" not in e.classes]
    UserInteraction(user, {next(iter(user.find(marker="undo").elements))}, None).click()
    assert store.message(mid).text == "drop the lanp" and store.message(mid).edited_at is None

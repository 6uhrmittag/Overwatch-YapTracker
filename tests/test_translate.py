"""Translate a chat line with DeepL (#468): off by default, the user's own key, only the line's
text is sent, errors in words. A fake DeepL answers: no network in tests or CI."""

import io
import json
import time
import urllib.error

import pytest
from nicegui.testing import User, user_simulation
from nicegui.testing.user_interaction import UserInteraction

from yaptracker import config, runtime, translate
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.store.repo import Store
from yaptracker.translate import DeepL, FakeTranslator, Translation
from yaptracker.ui import shell

KEY = "00000000-0000-0000-0000-000000000000:fx"  # made up
NOW = time.time()


class FakeDeepL:
    """What api-free.deepl.com would answer; keeps every request."""

    def __init__(self, answer=None, error=None):
        self.sent, self.answer, self.error = [], answer, error

    def __call__(self, request):
        self.sent.append(request)
        if self.error is not None:
            raise self.error
        return self.answer or {"translations": [{"detected_source_language": "ES",
                                                 "text": "gg, nice heals"}]}  # fmt: skip


def http_error(code):
    return urllib.error.HTTPError(translate.URL, code, "no", {}, io.BytesIO(b""))


def test_only_the_lines_text_and_the_target_language_are_sent():
    fake = FakeDeepL()
    deepl = DeepL(lambda: KEY, lambda: "EN", send=fake)
    assert deepl.translate("gg, buenas curas") == Translation("gg, nice heals", "Spanish")
    (request,) = fake.sent
    assert request.full_url == "https://api-free.deepl.com/v2/translate"
    assert request.get_method() == "POST"
    assert json.loads(request.data) == {"text": ["gg, buenas curas"], "target_lang": "EN-US"}
    assert {k.lower(): v for k, v in request.header_items()} == {
        "authorization": f"DeepL-Auth-Key {KEY}",
        "content-type": "application/json",
        "user-agent": "YapTracker",
    }
    assert deepl.translate("gg, buenas curas").text == "gg, nice heals"
    assert len(fake.sent) == 1  # each text once a run


def test_german_is_asked_for_as_de():
    fake = FakeDeepL()
    DeepL(lambda: KEY, lambda: "DE", send=fake).translate("merci")
    assert json.loads(fake.sent[0].data)["target_lang"] == "DE"


@pytest.mark.parametrize(
    ("key", "error", "said"),
    [
        ("", None, translate.NO_KEY),
        ("1234-pro-key", None, translate.NOT_FREE),
        (KEY, http_error(403), translate.WRONG_KEY),
        (KEY, http_error(456), translate.QUOTA),
        (KEY, http_error(429), translate.TOO_MANY),
        (KEY, http_error(500), translate.FAILED),
        (KEY, urllib.error.URLError("offline"), translate.OFFLINE),
        (KEY, TimeoutError(), translate.OFFLINE),
    ],
)
def test_what_went_wrong_is_said_in_words_and_never_retried(key, error, said):
    fake = FakeDeepL(error=error)
    assert DeepL(lambda: key, lambda: "EN", send=fake).translate("hola") == Translation(error=said)
    assert len(fake.sent) == (1 if key == KEY else 0)  # no key: nothing goes out


def test_an_odd_answer_is_a_failed_line_not_a_crash():
    fake = FakeDeepL(answer={"translations": []})
    assert DeepL(lambda: KEY, lambda: "EN", send=fake).translate("hola").error == translate.FAILED


def test_off_by_default_with_no_key_and_english():
    assert config.translate_chat() is False
    assert config.deepl_key() == "" and config.translate_to() == "EN"


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    yield s
    s.close()


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


def a_match(store):
    tracker = MatchTracker(store, Pause())
    tracker.capture_alive(NOW)
    tracker.new_match()
    pid = store.add_player("Pickle", NOW)
    store.add_message(ts=NOW, channel="match", speaker_raw="Pickle", player_id=pid,
                      text="gg buenas curas", match_id=tracker.match_id)  # fmt: skip
    store.add_message(ts=NOW + 1, channel="system", text="You endorsed Pickle!",
                      match_id=tracker.match_id)  # fmt: skip
    return tracker


async def test_settings_switch_key_and_language(user: User):
    config.save_setup_state("done")
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("Only the text of a line you translate goes to DeepL")
    user.find(marker="translate-switch").click()
    assert config.translate_chat() is True
    user.find(marker="deepl-key").type(KEY).trigger("blur")
    assert config.deepl_key() == KEY
    user.find(marker="translate-to-DE").click()
    assert config.translate_to() == "DE"


async def test_translate_in_live_only_while_switched_on(user: User, store, monkeypatch):
    config.save_setup_state("done")
    tracker = a_match(store)
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "matches", tracker)
    monkeypatch.setattr(runtime, "translator", FakeTranslator())
    await user.open("/")
    await user.should_see("gg buenas curas")
    await user.should_not_see(marker="translate-line")  # off by default
    config.save_translate_chat(True)
    await user.open("/")
    await user.should_see("gg buenas curas")
    (button,) = user.find(marker="translate-line").elements  # not on the system line
    UserInteraction(user, {button}, None).click()
    await user.should_see("↳ “(made-up translation of) gg buenas curas” (from Spanish)")


async def test_translate_in_a_profile_says_what_went_wrong_and_tries_again(
    user: User, store, monkeypatch
):
    config.save_setup_state("done")
    config.save_translate_chat(True)
    a_match(store)
    key = {"now": ""}  # no key yet
    monkeypatch.setattr(runtime, "store", store)
    monkeypatch.setattr(runtime, "translator", DeepL(lambda: key["now"], lambda: "EN",
                                                     send=FakeDeepL()))  # fmt: skip
    await user.open("/")
    user.find(marker="nav-yappers").click()
    user.find(marker="yapper").click()
    await user.should_see("Your verdict")
    user.find(marker="translate-line").click()
    await user.should_see(f"\u21b3 {translate.NO_KEY}")
    key["now"] = KEY
    user.find(marker="translate-line").click()  # again: in the same place
    await user.should_see("\u21b3 \u201cgg, nice heals\u201d (from Spanish)")
    assert len(user.find(marker="translation").elements) == 1
